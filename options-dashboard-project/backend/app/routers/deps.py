from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db


def get_session_id(
    x_session_id: str | None = Header(default=None),
    session_id: str | None = Cookie(default=None),
) -> str | None:
    """Session ID from the X-Session-Id header, falling back to the cookie.

    The header is the primary transport: the frontend and backend live on
    different sites (Vercel/Railway), so browsers that block third-party
    cookies would never send the session cookie cross-site."""
    return x_session_id or session_id


@dataclass(frozen=True)
class AuthenticatedUser:
    """Canonical application identity resolved from a session.

    ``user_id`` is the durable ``users.id`` (UUID) — the application-level
    identity that every data query must use.  ``access_token`` is the broker
    token required for Upstox API calls.
    """
    user_id: str
    access_token: str


def _extract_session_id(
    x_session_id: str | None,
    session_id_cookie: str | None,
) -> str:
    """Extract session ID from header/cookie, raising 401 if absent."""
    sid = x_session_id or session_id_cookie
    if not sid:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return sid


def _resolve_user(db: Session, sid: str) -> AuthenticatedUser:
    """Core resolution: session_id → (user_id, access_token).

    Phase 10.2B-3: token_store.get_token() now has DB fallback, so this
    function works across server restarts (memory → DB → decrypt → cache).

    Raises 401/403 on any failure.  Pure logic, no DI.
    """
    from app.identity import get_active_session, User
    from app.services import token_store

    token = token_store.get_token(sid)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")

    session = get_active_session(db, sid)
    if session is None:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")

    user = db.query(User).filter(User.id == session.user_id).one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=403, detail="StrikeNova account is not active.")

    return AuthenticatedUser(user_id=user.id, access_token=token)


def get_current_user(
    x_session_id: str | None = Header(default=None),
    session_id_cookie: str | None = Cookie(default=None, alias="session_id"),
) -> AuthenticatedUser:
    """Resolve session → user identity WITHOUT a shared DB session.

    Creates its own ``SessionLocal`` connection.  Use this when the endpoint
    does NOT need a ``db: Session = Depends(get_db)`` parameter (e.g.
    market-status, broker-profile that only need the access token).

    Phase 10.2A canonical dependency — uses ``user.id`` (UUID) as the
    application-level identity.  ``session_id`` is transport-only.
    """
    sid = _extract_session_id(x_session_id, session_id_cookie)
    from app.db import SessionLocal
    own_db = SessionLocal()
    try:
        return _resolve_user(own_db, sid)
    finally:
        own_db.close()


class CurrentUser:
    """FastAPI dependency class that shares the request's DB session.

    Usage in an endpoint::

        user: AuthenticatedUser = Depends(CurrentUser())

    This resolves ``db: Session = Depends(get_db)`` first, then queries the
    ``users`` / ``user_sessions`` tables on that same connection — avoiding a
    second connection and keeping tests on the same in-memory database.

    For endpoints that do NOT need a ``db`` parameter, use the simpler
    ``get_current_user`` function dependency instead.
    """

    def __call__(
        self,
        db: Session = Depends(get_db),
        x_session_id: str | None = Header(default=None),
        session_id_cookie: str | None = Cookie(default=None, alias="session_id"),
    ) -> AuthenticatedUser:
        sid = _extract_session_id(x_session_id, session_id_cookie)
        return _resolve_user(db, sid)
