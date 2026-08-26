import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError
from app.brokers.gateway import gateway
from app.routers.deps import get_session_id
from app.services import token_store
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

SESSION_COOKIE = "session_id"


@router.get("/login")
def login():
    """Redirects the browser to the broker's login page (via the gateway)."""
    state = token_store.create_oauth_state()
    adapter = gateway.create(BROKER_ID_UPSTOX)
    return RedirectResponse(adapter.get_authorization_url(state))


@router.get("/callback")
async def callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    """The broker redirects here after the user logs in on their site."""
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(error)}")
    if not token_store.consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        adapter = gateway.create(BROKER_ID_UPSTOX)
        access_token = await adapter.exchange_authorization_code(code)
    except BrokerError as e:
        logger.error("Token exchange failed: %s", e)
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(e.message)}")
    session_id = token_store.set_token(access_token)

    # Phase 7.24.8: Also persist the token for CLI tools.
    try:
        from app.services.upstox_token_manager import UpstoxTokenManager
        from datetime import datetime, timedelta, timezone
        _mgr = UpstoxTokenManager()
        _mgr.save(access_token, expires_at=datetime.now(timezone.utc) + timedelta(hours=24))
    except Exception:
        logger.debug("Could not persist token to cache (non-critical)")

    # Send the user back to the dashboard, now logged in. The session ID is
    # passed in the URL fragment (never sent to servers) because the frontend
    # and backend are on different sites, so browsers that block third-party
    # cookies would drop the cookie on later API calls.
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
    """Frontend calls this to check if we currently have a valid session."""
    return {"logged_in": token_store.get_token(session_id) is not None}


@router.post("/logout")
def logout(session_id: str | None = Depends(get_session_id)):
    if token_store.get_token(session_id) is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    token_store.clear_token()
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="none")
    return response
