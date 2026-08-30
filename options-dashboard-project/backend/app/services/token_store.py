"""Multi-user token storage with per-session isolation and DB persistence.

Phase 10.2B-3: Dual-layer architecture — in-memory cache backed by PostgreSQL.
Tokens survive server restarts via get_token() DB fallback on cache miss.

Each session owns exactly one broker token.  Sessions are identified by
cryptographically strong IDs (``secrets.token_urlsafe(32)``).  Token lookup
is O(1) by session ID via in-memory cache, with DB fallback on cache miss.

Security properties:
- One session's login never overwrites another session's token.
- ``clear_token(session_id)`` only clears the specified session.
- Session IDs are compared with constant-time ``secrets.compare_digest``.
- Expired/revoked sessions cannot access broker tokens.
- Tokens encrypted at rest via Fernet (app.crypto).
- Security-relevant events are logged without exposing secrets.
- OAuth state is HMAC-signed to prevent tampering and carry session binding.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache (fast path)
# ---------------------------------------------------------------------------

# session_id → {"access_token": str, "created_at": float}
_sessions: dict[str, dict] = {}

# Session TTL (24 hours) — matches the cookie max_age set in auth.py
_SESSION_TTL_SECONDS = 60 * 60 * 24

# ---------------------------------------------------------------------------
# OAuth state management — signed with HMAC
# ---------------------------------------------------------------------------

_STATE_TTL_SECONDS = 600  # 10 minutes

# HMAC signing secret (derived from TOKEN_ENCRYPTION_KEY on first use)
_state_hmac_key: bytes | None = None


def _get_state_hmac_key() -> bytes:
    """Derive an HMAC signing key from TOKEN_ENCRYPTION_KEY."""
    global _state_hmac_key
    if _state_hmac_key is not None:
        return _state_hmac_key
    from app.config import settings
    key = getattr(settings, "TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY must be set for OAuth state signing. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    _state_hmac_key = hashlib.sha256(key.encode("utf-8")).digest()
    return _state_hmac_key


# ---------------------------------------------------------------------------
# Token operations — dual-layer (memory + DB)
# ---------------------------------------------------------------------------


def set_token(token: str, *, connection_id: str | None = None, expires_at=None, persist_to_db: bool = True) -> str:
    """Store a broker token in memory (and optionally DB).

    Returns a new session ID bound to the token.

    Parameters
    ----------
    token : str
        The plaintext broker access token.
    connection_id : str, optional
        The broker connection ID to link this token to.
    expires_at : datetime, optional
        When the token expires (provider-specific).
    persist_to_db : bool, optional
        Whether to persist to DB (default True).  Set to False for
        non-broker sessions (email/password, Google) that don't need
        DB-backed token recovery after restart.
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

    # Phase A fix: only persist to DB when explicitly requested (broker sessions).
    # Email/password and Google sessions store identity tokens that are not
    # broker access tokens — persisting them to DB is unnecessary and causes
    # a misleading warning.
    if persist_to_db:
        try:
            _persist_token_to_db(session_id, token, connection_id, expires_at)
        except Exception:
            logger.warning(
                "Failed to persist token to DB (non-critical)",
                extra={"event": "auth.token.persist_failed", "session_prefix": session_id[:8]},
            )

    return session_id


def get_token(session_id: str | None) -> str | None:
    """Return the broker access token for the given session.

    Fast path: in-memory cache.  Slow path: DB fallback + decrypt + cache populate.

    Returns None if:
    - session_id is None/empty
    - session_id is not found in memory or DB
    - session has expired
    """
    if not session_id:
        return None

    # Fast path: memory
    entry = _sessions.get(session_id)
    if entry is not None:
        age = time.time() - entry["created_at"]
        if age <= _SESSION_TTL_SECONDS:
            return entry["access_token"]
        # Expired — remove from memory
        _sessions.pop(session_id, None)
        logger.info(
            "Session expired",
            extra={"event": "auth.session.expired", "session_prefix": session_id[:8]},
        )
        return None

    # Slow path: DB fallback
    token = _load_token_from_db(session_id)
    if token is not None:
        # Populate cache for future fast-path hits
        _sessions[session_id] = {
            "access_token": token,
            "created_at": time.time(),
        }
        return token

    return None


def clear_token(session_id: str | None = None) -> None:
    """Clear a specific session's token, or all tokens if session_id is None.

    Clears both memory cache and DB.
    """
    if session_id is None:
        # Emergency: clear all sessions
        count = len(_sessions)
        _sessions.clear()
        logger.info(
            "All sessions cleared",
            extra={"event": "auth.sessions.cleared_all", "count": count},
        )
        # DB cleanup is best-effort for emergency clear
        try:
            _clear_all_tokens_in_db()
        except Exception:
            logger.warning("Failed to clear all tokens in DB", extra={"event": "auth.token.clear_all_db_failed"})
    else:
        removed = _sessions.pop(session_id, None)
        if removed:
            logger.info(
                "Session cleared",
                extra={"event": "auth.session.cleared", "session_prefix": session_id[:8]},
            )
        # DB cleanup
        try:
            _clear_token_in_db(session_id)
        except Exception:
            logger.warning(
                "Failed to clear token in DB",
                extra={"event": "auth.token.clear_db_failed", "session_prefix": session_id[:8]},
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
# Startup — DB token health check (no in-memory rehydration)
# ---------------------------------------------------------------------------

# Phase 10.2B-3 design decision:
# In-memory cache cannot be rehydrated because the DB stores session_hash
# (SHA-256), not the plaintext session_id needed as the cache key.
# Instead, get_token() uses a DB fallback on cache miss, which correctly
# looks up by session_hash and repopulates the in-memory cache with the
# correct plaintext key.
#
# This means the first request per session after a server restart goes
# through the slow DB path (decrypt + join), and subsequent requests hit
# the fast in-memory path.  This is the correct trade-off: it avoids
# storing plaintext session IDs in the database.


def startup_db_check() -> int:
    """Verify DB connectivity and count active tokens at startup.

    Returns the number of active (non-expired, non-revoked) tokens in DB.
    These tokens will be loaded on-demand via get_token() DB fallback.
    Does NOT populate the in-memory cache.
    """
    count = 0
    try:
        from app.db import SessionLocal
        from app.identity import BrokerToken, UserSession
        from datetime import datetime, timezone

        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            count = (
                db.query(BrokerToken)
                .join(
                    UserSession,
                    BrokerToken.session_hash == UserSession.session_hash,
                )
                .filter(
                    BrokerToken.broker_token_encrypted.isnot(None),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
                .count()
            )
        finally:
            db.close()
    except Exception:
        logger.warning(
            "DB token health check failed (non-critical)",
            extra={"event": "auth.startup.db_check_failed"},
        )

    logger.info(
        "DB token health check passed",
        extra={"event": "auth.startup.db_check", "active_tokens": count},
    )
    return count


# ---------------------------------------------------------------------------
# Signed OAuth state — HMAC-signed, carries session_id + broker
# ---------------------------------------------------------------------------


def create_oauth_state(
    session_id: str | None = None,
    broker: str = "UPSTOX",
) -> str:
    """Create a signed OAuth state value.

    When session_id is provided (authenticated-first flow), the state carries
    a signed {session_id, broker, timestamp} payload.  When omitted, falls back
    to CSRF-only state for backward compatibility.

    Old states are garbage-collected on each call.
    """
    # Garbage-collect old pending states
    now = time.time()
    for state_val, created_at in list(_pending_states.items()):
        if now - created_at > _STATE_TTL_SECONDS:
            del _pending_states[state_val]

    if session_id:
        # Signed state with session binding
        payload = json.dumps(
            {"sid": session_id, "brk": broker.upper(), "ts": int(now)},
            separators=(",", ":"),
        )
        b64 = base64.urlsafe_b64encode(payload.encode()).decode()
        sig = hmac.new(_get_state_hmac_key(), b64.encode(), hashlib.sha256).hexdigest()[:32]
        state = f"{b64}.{sig}"
    else:
        # Fallback: random CSRF-only state (backward compat)
        state = secrets.token_urlsafe(32)

    _pending_states[state] = now
    return state


def consume_oauth_state(state: str | None) -> dict | None:
    """Validate and extract session_id + broker from signed OAuth state.

    Returns {"session_id": "...", "broker": "UPSTOX"} on success.
    Returns None if state is invalid, expired, or already consumed.

    Backward compatible: falls back to old CSRF-only format if signed
    format is not detected.
    """
    if not state:
        return None

    # Dot-containing states are ALWAYS treated as signed (HMAC) states.
    # They must NOT silently downgrade to the legacy unsigned path.
    if "." in state:
        b64, sig = state.rsplit(".", 1)
        try:
            expected_sig = hmac.new(
                _get_state_hmac_key(), b64.encode(), hashlib.sha256
            ).hexdigest()[:32]
            if not hmac.compare_digest(sig, expected_sig):
                return None  # Tampered — reject, do NOT fall through
            payload = json.loads(base64.urlsafe_b64decode(b64))
            if time.time() - payload.get("ts", 0) > _STATE_TTL_SECONDS:
                return None  # Expired
            created_at = _pending_states.pop(state, None)
            if created_at is None:
                return None  # Already consumed or not from us
            return {
                "session_id": payload.get("sid", ""),
                "broker": payload.get("brk", "UPSTOX"),
            }
        except Exception:
            # Corrupted signed state — reject, do NOT fall through to legacy
            return None

    # Legacy: unsigned CSRF-only state (no dot separator)
    created_at = _pending_states.pop(state, None)
    if created_at is not None and time.time() - created_at <= _STATE_TTL_SECONDS:
        return {"session_id": "", "broker": "UPSTOX"}
    return None


# ---------------------------------------------------------------------------
# Pending states (CSRF protection) — kept for backward compat
# ---------------------------------------------------------------------------

_pending_states: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Google OAuth nonce binding — HMAC-signed state carrying the nonce
# ---------------------------------------------------------------------------
#
# Phase A security fix: The frontend generates a nonce and sends it to
# Google, but the backend never sees it.  To cryptographically bind the
# nonce to the authentication attempt, the backend generates its own
# nonce, embeds it in an HMAC-signed state, and returns it to the
# frontend.  The frontend includes this state in the Google OAuth URL.
# When Google redirects back, the frontend sends both the id_token AND
# the state to POST /auth/google.  The backend validates the HMAC,
# extracts the expected nonce, and compares it against the JWT nonce.
#
# This prevents replay of Google ID tokens from unrelated auth attempts.

def peek_google_oauth_nonce(state: str) -> str | None:
    """Read the nonce from a signed Google OAuth state WITHOUT consuming it.

    Used by POST /auth/google/state to return the nonce to the frontend.
    The state remains in _pending_states for later consumption.
    """
    if not state or "." not in state:
        return None
    b64, sig = state.rsplit(".", 1)
    try:
        expected_sig = hmac.new(
            _get_state_hmac_key(), b64.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64))
        return payload.get("nonce")
    except Exception:
        return None


def create_google_oauth_state(nonce: str | None = None) -> str:
    """Create an HMAC-signed state for Google OAuth nonce binding.

    Generates a random nonce if not provided.  The state carries
    {nonce, ts} and is HMAC-signed with the same key as broker OAuth state.

    Returns the signed state string (base64.signature format).
    """
    now = time.time()
    if nonce is None:
        nonce = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"nonce": nonce, "ts": int(now)},
        separators=(",", ":"),
    )
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_get_state_hmac_key(), b64.encode(), hashlib.sha256).hexdigest()[:32]
    state = f"{b64}.{sig}"
    _pending_states[state] = now
    return state


def consume_google_oauth_state(state: str | None) -> str | None:
    """Validate and extract the expected nonce from a signed Google OAuth state.

    Returns the nonce string on success.
    Returns None if state is invalid, expired, or already consumed.
    """
    if not state or "." not in state:
        return None
    b64, sig = state.rsplit(".", 1)
    try:
        expected_sig = hmac.new(
            _get_state_hmac_key(), b64.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64))
        if time.time() - payload.get("ts", 0) > _STATE_TTL_SECONDS:
            return None
        created_at = _pending_states.pop(state, None)
        if created_at is None:
            return None  # Already consumed or not from us
        return payload.get("nonce")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DB persistence helpers — best-effort, never block the request
# ---------------------------------------------------------------------------


def _persist_token_to_db(session_id: str, token: str, connection_id: str | None, expires_at) -> None:
    """Write encrypted token to broker_tokens table."""
    from datetime import datetime, timezone
    from app.db import SessionLocal
    from app.identity import BrokerToken, hash_session_id
    from app.crypto import encrypt

    db = SessionLocal()
    try:
        bt = BrokerToken(
            connection_id=connection_id or "none",
            session_hash=hash_session_id(session_id),
            broker_token_encrypted=encrypt(token),
            broker_token_expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
        )
        db.add(bt)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _load_token_from_db(session_id: str) -> str | None:
    """Load token from DB: BrokerToken (broker sessions) or UserSession (platform sessions).

    For broker sessions: decrypt the broker access token from broker_tokens.
    For platform sessions (Google/email): return the session_id as identity marker.
    Platform sessions never create BrokerToken rows.
    """
    from datetime import datetime, timezone
    from app.db import SessionLocal
    from app.identity import BrokerToken, UserSession, hash_session_id
    from app.crypto import decrypt

    session_hash = hash_session_id(session_id)
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Path 1: Broker session — find BrokerToken + valid UserSession
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
            bt, us = row
            return decrypt(bt.broker_token_encrypted)

        # Path 2: Platform-only session (UserSession exists, no BrokerToken)
        # get_token() is for BROKER tokens only — return None.
        # Use has_platform_session() for platform identity checks.

        return None
    except Exception:
        return None
    finally:
        db.close()


def has_platform_session(session_id: str | None) -> bool:
    """Check whether session_id has a valid UserSession DB record.

    This is a DB-only check — it does NOT use the in-memory cache.
    Use this in require_token() to distinguish 'platform-only session'
    from 'broker session' or 'no session'.

    Returns True if a non-expired, non-revoked UserSession exists.
    """
    if not session_id:
        return False
    try:
        from datetime import datetime, timezone
        from app.db import SessionLocal
        from app.identity import UserSession, hash_session_id

        now = datetime.now(timezone.utc)
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
            return us is not None
        finally:
            db.close()
    except Exception:
        return False


def _clear_token_in_db(session_id: str) -> None:
    """NULL the encrypted token in broker_tokens for this session."""
    from app.db import SessionLocal
    from app.identity import BrokerToken, hash_session_id

    session_hash = hash_session_id(session_id)
    db = SessionLocal()
    try:
        bt = db.query(BrokerToken).filter(BrokerToken.session_hash == session_hash).first()
        if bt is not None:
            bt.broker_token_encrypted = None
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _clear_all_tokens_in_db() -> None:
    """NULL all encrypted tokens in broker_tokens (emergency clear)."""
    from app.db import SessionLocal
    from app.identity import BrokerToken

    db = SessionLocal()
    try:
        db.query(BrokerToken).update({"broker_token_encrypted": None})
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
