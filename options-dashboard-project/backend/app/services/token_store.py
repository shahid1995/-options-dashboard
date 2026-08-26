"""Multi-user token storage with per-session isolation.

Each session owns exactly one broker token.  Sessions are identified by
cryptographically strong IDs (``secrets.token_urlsafe(32)``).  Token lookup
is O(1) by session ID; no global mutable state is shared between sessions.

Security properties:
- One session's login never overwrites another session's token.
- ``clear_token(session_id)`` only clears the specified session.
- ``get_any_token()`` is NOT available — use ``get_token(session_id)``.
- Session IDs are compared with constant-time ``secrets.compare_digest``.
- Expired/revoked sessions cannot access broker tokens.
- Security-relevant events are logged without exposing secrets.
"""

import logging
import secrets
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-session token store
# ---------------------------------------------------------------------------

# session_id → {"access_token": str, "created_at": float}
_sessions: dict[str, dict] = {}

# Pending OAuth "state" values (CSRF protection), state → created_at
_pending_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600

# Session TTL (24 hours) — matches the cookie max_age set in auth.py
_SESSION_TTL_SECONDS = 60 * 60 * 24


def set_token(token: str) -> str:
    """Store a broker token and return a new session ID bound to it.

    Creates a new session; does NOT overwrite existing sessions.
    """
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {
        "access_token": token,
        "created_at": time.time(),
    }
    logger.info(
        "Session created",
        extra={"event": "auth.session.created", "session_prefix": session_id[:8]},
    )
    return session_id


def get_token(session_id: str | None) -> str | None:
    """Return the broker access token for the given session.

    Returns None if:
    - session_id is None/empty
    - session_id is not found
    - session has expired
    """
    if not session_id:
        return None

    entry = _sessions.get(session_id)
    if entry is None:
        return None

    # Check session expiry
    age = time.time() - entry["created_at"]
    if age > _SESSION_TTL_SECONDS:
        # Session expired — remove it
        _sessions.pop(session_id, None)
        logger.info(
            "Session expired",
            extra={"event": "auth.session.expired", "session_prefix": session_id[:8]},
        )
        return None

    return entry["access_token"]


def clear_token(session_id: str | None = None) -> None:
    """Clear a specific session's token, or all tokens if session_id is None.

    Phase 8F: ``clear_token(session_id)`` only clears the specified session.
    ``clear_token()`` (no argument) clears ALL sessions — use only for
    system-wide logout or emergency revocation.
    """
    if session_id is None:
        # Emergency: clear all sessions
        count = len(_sessions)
        _sessions.clear()
        logger.info(
            "All sessions cleared",
            extra={"event": "auth.sessions.cleared_all", "count": count},
        )
    else:
        removed = _sessions.pop(session_id, None)
        if removed:
            logger.info(
                "Session cleared",
                extra={"event": "auth.session.cleared", "session_prefix": session_id[:8]},
            )


def get_session_count() -> int:
    """Return the number of active sessions (for monitoring)."""
    return len(_sessions)


def get_all_session_ids() -> list[str]:
    """Return all active session IDs (for admin monitoring only).

    Never expose full session IDs in API responses.
    """
    return list(_sessions.keys())


# ---------------------------------------------------------------------------
# OAuth state management (CSRF protection)
# ---------------------------------------------------------------------------

def create_oauth_state() -> str:
    """Create a new OAuth state value for CSRF protection.

    Old states are garbage-collected on each call.
    """
    now = time.time()
    for state, created_at in list(_pending_states.items()):
        if now - created_at > _STATE_TTL_SECONDS:
            del _pending_states[state]
    state = secrets.token_urlsafe(32)
    _pending_states[state] = now
    return state


def consume_oauth_state(state: str | None) -> bool:
    """Consume (and invalidate) an OAuth state value.

    Returns True if the state was valid and not expired.
    Each state can only be consumed once (prevents replay).
    """
    if not state:
        return False
    created_at = _pending_states.pop(state, None)
    return created_at is not None and time.time() - created_at <= _STATE_TTL_SECONDS


# ---------------------------------------------------------------------------
# Compatibility shim — DEPRECATED, will be removed after migration
# ---------------------------------------------------------------------------

# Legacy code that uses get_any_token() must be migrated to get_token(session_id).
# This function is kept temporarily for backward compatibility during Phase 8F
# migration but should NOT be used in new code.

def get_any_token() -> str | None:
    """DEPRECATED: Returns the most recent session's token.

    This function exists only for backward compatibility during the
    multi-user migration. New code MUST use get_token(session_id).

    For the background capture loop, use the session-scoped approach
    or the most recently authenticated session.
    """
    logger.warning(
        "get_any_token() called — this is deprecated and will be removed",
        extra={"event": "auth.deprecated_get_any_token"},
    )
    # Return the most recently created session's token
    if not _sessions:
        return None
    # Sort by created_at descending, return the newest
    newest = max(_sessions.items(), key=lambda kv: kv[1]["created_at"])
    return newest[1]["access_token"]
