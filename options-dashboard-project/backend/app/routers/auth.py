import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError
from app.brokers.gateway import gateway
from app.config import settings
from app.db import SessionLocal
from app.identity import (
    create_session_record,
    get_active_session,
    get_or_create_user_from_upstox,
    revoke_session,
)
from app.routers.deps import get_session_id
from app.services import token_store

logger = logging.getLogger(__name__)

router = APIRouter()

SESSION_COOKIE = "session_id"


@router.get("/login")
def login():
    """Redirect the browser to the broker's login page via the gateway."""
    state = token_store.create_oauth_state()
    adapter = gateway.create(BROKER_ID_UPSTOX)
    return RedirectResponse(adapter.get_authorization_url(state))


@router.get("/callback")
async def callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    """Complete broker OAuth and bind the session to a durable StrikeNova user."""
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(error)}")
    if not token_store.consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        adapter = gateway.create(BROKER_ID_UPSTOX)
        access_token = await adapter.exchange_authorization_code(code)
        # Upstox's authenticated profile supplies the stable broker user ID
        # that becomes the external identity key for the StrikeNova account.
        profile = await gateway.create(BROKER_ID_UPSTOX, access_token=access_token).get_profile()
    except BrokerError as e:
        logger.error("Token/profile exchange failed: %s", e)
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(e.message)}")

    # Phase 10.1: persist StrikeNova identity and durable session ownership.
    # The broker access token itself remains exclusively in token_store.
    # Schema is managed by Alembic migrations (Phase 10.1A), not runtime create_all.
    db = SessionLocal()
    session_id = None
    try:
        user = get_or_create_user_from_upstox(db, profile)
        if user.status != "active":
            db.rollback()
            raise HTTPException(status_code=403, detail="StrikeNova account is not active")

        session_id = token_store.set_token(access_token)
        create_session_record(db, user.id, session_id)
    except HTTPException:
        if session_id:
            token_store.clear_token(session_id)
        raise
    except Exception:
        db.rollback()
        if session_id:
            token_store.clear_token(session_id)
        logger.exception("Failed to persist StrikeNova identity/session")
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error=account_setup_failed")
    finally:
        db.close()

    # Phase 7.24.8: Also persist the token for CLI tools.
    try:
        from app.services.upstox_token_manager import UpstoxTokenManager

        _mgr = UpstoxTokenManager()
        _mgr.save(access_token, expires_at=datetime.now(timezone.utc) + timedelta(hours=24))
    except Exception:
        logger.debug("Could not persist token to cache (non-critical)")

    # Send the user back to the dashboard. The session ID is passed in the
    # URL fragment because it is not sent to servers as a query parameter.
    response = RedirectResponse(f"{settings.FRONTEND_URL}/dashboard#session_id={session_id}")
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=60 * 60 * 24,
    )
    return response


@router.get("/status")
def status(session_id: str | None = Depends(get_session_id)):
    """Frontend calls this to check if the current session is valid."""
    return {"logged_in": token_store.get_token(session_id) is not None}


@router.get("/me")
def me(session_id: str | None = Depends(get_session_id)):
    """Return the authenticated StrikeNova account without broker secrets."""
    if token_store.get_token(session_id) is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    # Schema is managed by Alembic migrations (Phase 10.1A).
    db = SessionLocal()
    try:
        session = get_active_session(db, session_id)
        if session is None:
            raise HTTPException(status_code=401, detail="StrikeNova session is invalid or expired")

        from app.identity import User

        user = db.query(User).filter(User.id == session.user_id).one_or_none()
        if user is None or user.status != "active":
            raise HTTPException(status_code=403, detail="StrikeNova account is not active")

        return {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
            "identity_source": user.identity_source,
            "broker_provider": user.broker_provider,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }
    finally:
        db.close()


@router.post("/logout")
def logout(session_id: str | None = Depends(get_session_id)):
    if token_store.get_token(session_id) is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    # Schema is managed by Alembic migrations (Phase 10.1A).
    db = SessionLocal()
    try:
        revoke_session(db, session_id)
    finally:
        db.close()

    token_store.clear_token(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="none")
    return response
