import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse, RedirectResponse

from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError
from app.brokers.gateway import gateway
from app.config import settings
from app.db import SessionLocal, get_db
from app.identity import (
    BrokerConnection,
    UserSession,
    create_session_record,
    get_active_session,
    get_or_create_connection,
    get_or_create_user_from_upstox,
    get_analytics_token,
    remove_analytics_token,
    resolve_user_credentials,
    revoke_session,
    store_analytics_token,
    store_credentials,
)
from app.routers.deps import CurrentUser, AuthenticatedUser, get_session_id
from app.services import token_store

logger = logging.getLogger(__name__)

router = APIRouter()

SESSION_COOKIE = "session_id"


# ---------------------------------------------------------------------------
# GET /auth/login — Phase 10.2B-2: BYOB-aware login
# ---------------------------------------------------------------------------

@router.get("/login")
def login(
    broker: str = Query(default="UPSTOX"),
    session_id: str | None = Depends(get_session_id),
):
    """Redirect the browser to the broker's OAuth login page.

    BYOB path: if the user is authenticated and has stored credentials
    for this broker, use their per-user API key for the OAuth URL.
    Fallback: use platform-level settings.UPSTOX_API_KEY (backward compat).

    The user MUST be authenticated (have a valid session) to initiate
    BYOB OAuth.  This avoids the OAuth-state-to-user-identity problem
    entirely (authenticated-first flow).
    """
    broker_id = broker.upper()

    # Try to resolve user's per-user credentials (BYOB path)
    user_credentials: dict = {}
    if session_id:
        token = token_store.get_token(session_id)
        if token is not None:
            # User is authenticated — try to find their broker credentials
            db = SessionLocal()
            try:
                session = get_active_session(db, session_id)
                if session is not None:
                    try:
                        user_credentials = resolve_user_credentials(
                            session.user_id, broker_id, db
                        )
                    except ValueError:
                        pass  # No stored credentials — fall back to platform key
            finally:
                db.close()

    # Phase 10.2B-3: Embed session_id in signed OAuth state for callback binding.
    # This eliminates the race condition where the callback couldn't identify
    # which user initiated the OAuth flow.
    if session_id and token_store.get_token(session_id):
        state = token_store.create_oauth_state(session_id=session_id, broker=broker_id)
    else:
        state = token_store.create_oauth_state()  # fallback: no session binding

    adapter = gateway.create(broker_id, **user_credentials)
    return RedirectResponse(adapter.get_authorization_url(state))


# ---------------------------------------------------------------------------
# GET /auth/callback — Phase 10.2B-2: BYOB-aware callback
# ---------------------------------------------------------------------------

@router.get("/callback")
async def callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    broker: str = Query(default="UPSTOX"),
):
    """Complete broker OAuth using USER's per-user credentials (BYOB).

    Both the authorization-code exchange AND the profile fetch use the
    SAME user's API key/secret.  No shared platform credentials in BYOB path.
    """
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(error)}")
    # Phase 10.2B-3: Extract session_id + broker from signed OAuth state.
    # This eliminates the race condition — we know EXACTLY which user initiated OAuth.
    state_data = token_store.consume_oauth_state(state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    bound_session_id = state_data.get("session_id", "")
    broker_id = state_data.get("broker", broker.upper())

    # Resolve user's per-user credentials from the bound session.
    # Deterministic: we know exactly which session initiated this OAuth flow.
    user_credentials: dict = {}
    user_id_for_connection: str | None = None

    if bound_session_id:
        pre_db = SessionLocal()
        try:
            session = get_active_session(pre_db, bound_session_id)
            if session is not None:
                user_id_for_connection = session.user_id
                try:
                    user_credentials = resolve_user_credentials(
                        user_id_for_connection, broker_id, pre_db
                    )
                except ValueError:
                    pass  # No stored credentials — will use platform key fallback
        finally:
            pre_db.close()

    try:
        # Create adapter with USER's credentials — both exchange and profile
        # use the same user's API key (single adapter creation, no double-bug)
        adapter = gateway.create(broker_id, **user_credentials)
        access_token = await adapter.exchange_authorization_code(code)
        profile = await gateway.create(
            broker_id, access_token=access_token, **user_credentials
        ).get_profile()
    except BrokerError as e:
        logger.error("Token/profile exchange failed: %s", e)
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(e.message)}")

    # Phase 10.1: persist StrikeNova identity and durable session ownership.
    db = SessionLocal()
    session_id = None
    try:
        user = get_or_create_user_from_upstox(db, profile)
        if user.status != "active":
            db.rollback()
            raise HTTPException(status_code=403, detail="StrikeNova account is not active")

        # Extract broker_account_id using adapter-specific logic (AD-6)
        broker_account_id = adapter.extract_account_id(profile)
        connection = None
        if broker_account_id:
            connection = get_or_create_connection(
                db, user.id, broker_id, broker_account_id
            )
        else:
            logger.warning(
                "Could not extract broker account ID from %s profile", broker_id
            )

        session_id = token_store.set_token(
            access_token,
            connection_id=connection.id if connection else None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        create_session_record(
            db, user.id, session_id,
            broker_connection_id=connection.id if connection else None,
        )
        db.commit()  # Commit all DB changes from this callback
    except HTTPException:
        if session_id:
            token_store.clear_token(session_id)
        raise
    except Exception:
        db.rollback()
        if session_id:
            token_store.clear_token(session_id)
        logger.exception("Failed to persist StrikeNova identity/session")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}?login_error=account_setup_failed"
        )
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
    response = RedirectResponse(
        f"{settings.FRONTEND_URL}/dashboard#session_id={session_id}"
    )
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=60 * 60 * 24,
    )
    return response


# ---------------------------------------------------------------------------
# POST /auth/connect — Phase 10.2B-2: Store broker credentials (BYOB)
# ---------------------------------------------------------------------------

@router.post("/connect")
def connect_broker(
    broker: str = Body(..., embed=True),
    api_key: str = Body(..., embed=True),
    api_secret: str = Body(..., embed=True),
    redirect_uri: str | None = Body(default=None, embed=True),
    display_label: str | None = Body(default=None, embed=True),
    user: AuthenticatedUser = Depends(CurrentUser()),
    db: Session = Depends(get_db),
):
    """Store a user's broker Developer App credentials (BYOB onboarding).

    The user must be authenticated to StrikeNova first.
    Credentials are encrypted and stored in broker_connections.

    Validation:
    - api_key and api_secret must be non-empty strings
    - Maximum length: 512 characters each
    """
    # Input validation
    api_key = api_key.strip()
    api_secret = api_secret.strip()

    if not api_key:
        raise HTTPException(status_code=422, detail="api_key must not be empty")
    if len(api_key) > 512:
        raise HTTPException(
            status_code=422, detail="api_key must be 512 characters or fewer"
        )
    if not api_secret:
        raise HTTPException(status_code=422, detail="api_secret must not be empty")
    if len(api_secret) > 512:
        raise HTTPException(
            status_code=422, detail="api_secret must be 512 characters or fewer"
        )

    conn = store_credentials(
        db,
        user_id=user.user_id,
        broker=broker,
        api_key=api_key,
        api_secret=api_secret,
        redirect_uri=redirect_uri,
        display_label=display_label,
    )
    db.commit()

    return {
        "ok": True,
        "connection_id": conn.id,
        "broker": conn.broker,
        "status": conn.status,
    }


# ---------------------------------------------------------------------------
# Remaining endpoints (unchanged from 10.2A)
# ---------------------------------------------------------------------------

@router.get("/status")
def status(session_id: str | None = Depends(get_session_id)):
    """Frontend calls this to check if the current session is valid."""
    return {"logged_in": token_store.get_token(session_id) is not None}


@router.get("/me")
def me(session_id: str | None = Depends(get_session_id), db: Session = Depends(get_db)):
    """Return the authenticated StrikeNova account without broker secrets."""
    if token_store.get_token(session_id) is None:
        raise HTTPException(status_code=401, detail="Not logged in")

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


@router.post("/logout")
def logout(session_id: str | None = Depends(get_session_id), db: Session = Depends(get_db)):
    if token_store.get_token(session_id) is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    revoke_session(db, session_id)
    db.commit()

    token_store.clear_token(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="none")
    return response


# ---------------------------------------------------------------------------
# Analytics Token endpoints (Phase 10.2B-4)
# ---------------------------------------------------------------------------


@router.post("/connect-analytics-token")
def connect_analytics_token(
    broker: str = Body(default="UPSTOX", embed=True),
    analytics_token: str = Body(..., embed=True),
    user: AuthenticatedUser = Depends(CurrentUser()),
    db: Session = Depends(get_db),
):
    """Store the user's Analytics Token for read-only market data access.

    The user must have an active broker connection for this broker.
    The Analytics Token is encrypted and stored on the broker_connection row.

    Validation:
    - analytics_token must be non-empty
    - Maximum length: 512 characters
    """
    analytics_token = analytics_token.strip()
    if not analytics_token:
        raise HTTPException(status_code=422, detail="analytics_token must not be empty")
    if len(analytics_token) > 512:
        raise HTTPException(
            status_code=422, detail="analytics_token must be 512 characters or fewer"
        )

    try:
        store_analytics_token(db, user.user_id, broker, analytics_token)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"ok": True, "broker": broker.upper(), "message": "Analytics Token stored"}


@router.get("/analytics-token/status")
def analytics_token_status(
    broker: str = Query(default="UPSTOX"),
    user: AuthenticatedUser = Depends(CurrentUser()),
    db: Session = Depends(get_db),
):
    """Check if the user has an Analytics Token stored for this broker.

    Does NOT return the actual token — only whether it exists.
    """
    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user.user_id,
            BrokerConnection.broker == broker.upper(),
            BrokerConnection.status == "connected",
            BrokerConnection.is_default == True,
        )
        .first()
    )
    if conn is None:
        return {
            "has_analytics_token": False,
            "broker": broker.upper(),
            "message": "No connected broker found",
        }

    return {
        "has_analytics_token": conn.broker_analytics_token_encrypted is not None,
        "broker": broker.upper(),
        "connection_id": conn.id,
    }


@router.delete("/analytics-token")
def delete_analytics_token(
    broker: str = Query(default="UPSTOX"),
    user: AuthenticatedUser = Depends(CurrentUser()),
    db: Session = Depends(get_db),
):
    """Remove the user's Analytics Token for this broker."""
    removed = remove_analytics_token(db, user.user_id, broker)
    db.commit()

    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No Analytics Token found for {broker.upper()}",
        )

    return {"ok": True, "broker": broker.upper(), "message": "Analytics Token removed"}
