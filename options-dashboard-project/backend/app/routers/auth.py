import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from app.services import upstox, token_store
from app.services.upstox import UpstoxError
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/login")
def login():
    """Redirects the browser to Upstox's login page."""
    return RedirectResponse(upstox.get_login_url())


@router.get("/callback")
async def callback(code: str | None = None, error: str | None = None):
    """Upstox redirects here after the user logs in on their site."""
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(error)}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        access_token = await upstox.exchange_code_for_token(code)
    except UpstoxError as e:
        logger.error("Token exchange failed: %s", e)
        return RedirectResponse(f"{settings.FRONTEND_URL}?login_error={quote(e.message)}")
    token_store.set_token(access_token)

    # Send the user back to the dashboard, now logged in
    return RedirectResponse(f"{settings.FRONTEND_URL}/dashboard")


@router.get("/status")
def status():
    """Frontend calls this to check if we currently have a valid session."""
    return {"logged_in": token_store.get_token() is not None}


@router.post("/logout")
def logout():
    token_store.clear_token()
    return {"ok": True}
