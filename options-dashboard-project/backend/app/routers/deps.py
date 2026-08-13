from fastapi import Cookie, Header


def get_session_id(
    x_session_id: str | None = Header(default=None),
    session_id: str | None = Cookie(default=None),
) -> str | None:
    """Session ID from the X-Session-Id header, falling back to the cookie.

    The header is the primary transport: the frontend and backend live on
    different sites (Vercel/Railway), so browsers that block third-party
    cookies would never send the session cookie cross-site."""
    return x_session_id or session_id
