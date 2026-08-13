# Very simple in-memory token storage for a single-user MVP.
#
# LIMITATION: if the server restarts, this token is lost and you'll need to
# log in again. Since Upstox tokens expire every day at 3:30 AM anyway,
# this is a fine trade-off for now. A future version can persist this
# to a database if multiple users need to log in.

import secrets
import time

_state = {"access_token": None, "session_id": None}

# Pending OAuth "state" values (CSRF protection), state -> created_at
_pending_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600


def set_token(token: str) -> str:
    """Stores the token and returns a new session id bound to it."""
    session_id = secrets.token_urlsafe(32)
    _state["access_token"] = token
    _state["session_id"] = session_id
    return session_id


def get_token(session_id: str | None) -> str | None:
    """Returns the token only for the session that logged in."""
    if not session_id or _state["session_id"] is None:
        return None
    if not secrets.compare_digest(session_id, _state["session_id"]):
        return None
    return _state["access_token"]


def clear_token() -> None:
    _state["access_token"] = None
    _state["session_id"] = None


def create_oauth_state() -> str:
    now = time.time()
    for state, created_at in list(_pending_states.items()):
        if now - created_at > _STATE_TTL_SECONDS:
            del _pending_states[state]
    state = secrets.token_urlsafe(32)
    _pending_states[state] = now
    return state


def consume_oauth_state(state: str | None) -> bool:
    if not state:
        return False
    created_at = _pending_states.pop(state, None)
    return created_at is not None and time.time() - created_at <= _STATE_TTL_SECONDS
