"""Persistent Upstox token manager — Phase 7.24.3.

Provides durable access-token storage so that CLI tools and background
processes can authenticate without requiring browser-based OAuth each time.

Architecture:

    Upstox OAuth callback (FastAPI)
              │
              ▼
    UpstoxTokenManager.save(access_token, expires_at)
              │
              ▼
    Persistent file (.token_cache/upstox_token.json)
              │
              ▼
    UpstoxTokenManager.get_token()
              │
              ▼
    UpstoxClient (Phase 7.24.2)

Key properties:
  - Token is persisted to a deterministic file path
  - Path is independent of the current working directory
  - Writes are atomic (temp → flush → rename)
  - Expiry is tracked with a configurable safety buffer
  - Corrupted/missing files are handled gracefully
  - Token never appears in logs, exceptions, or responses
  - Token is NOT stored in the SQLite database
  - Token cache is covered by .gitignore

No real Upstox API calls are made by this module.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.upstox_client import TokenProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token state
# ---------------------------------------------------------------------------

class TokenState(str, Enum):
    """Lifecycle states for a persisted token."""
    NO_TOKEN = "NO_TOKEN"
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    CORRUPTED = "CORRUPTED"


# ---------------------------------------------------------------------------
# Token manager
# ---------------------------------------------------------------------------

class UpstoxTokenManager(TokenProvider):
    """Persistent Upstox access-token manager.

    Stores the token in a JSON file at a deterministic path derived from
    the application source location (not the process working directory).

    Usage::

        manager = UpstoxTokenManager()
        manager.save("access_token_value", expires_at=datetime(...))

        # Later, in a different process / different CWD:
        manager = UpstoxTokenManager()
        token = manager.get_token()  # returns the persisted token or None

    The manager implements :class:`TokenProvider` so it can be passed
    directly to :class:`UpstoxClient`.
    """

    # Default safety buffer: consider token expired 5 minutes early
    DEFAULT_EXPIRY_BUFFER_SECONDS: int = 300  # 5 minutes

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        expiry_buffer_seconds: int | None = None,
    ) -> None:
        if cache_dir is None:
            # Deterministic path based on the backend application source
            # location.  This is independent of CWD.
            backend_dir = Path(__file__).resolve().parent.parent.parent
            cache_dir = backend_dir / ".token_cache"
        self._cache_dir = Path(cache_dir)
        self._token_file = self._cache_dir / "upstox_token.json"
        self._expiry_buffer = (
            expiry_buffer_seconds
            if expiry_buffer_seconds is not None
            else self.DEFAULT_EXPIRY_BUFFER_SECONDS
        )
        # In-memory cache (set on first load)
        self._cached: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # TokenProvider interface
    # ------------------------------------------------------------------

    def get_token(self) -> str | None:
        """Return the current access token, or None if unavailable/expired.

        This implements the TokenProvider protocol consumed by UpstoxClient.
        """
        state, data = self._load_state()
        if state in (TokenState.VALID, TokenState.EXPIRING_SOON):
            return data.get("access_token")
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_token(self) -> bool:
        """True if a non-expired token is cached."""
        return self.get_token() is not None

    def save(self, access_token: str, expires_at: datetime | None = None) -> None:
        """Persist the access token to disk using an atomic write.

        Parameters
        ----------
        access_token:
            The Upstox access token string.
        expires_at:
            Optional expiration datetime (timezone-aware preferred).
            If None, defaults to now + 24 hours.
        """
        if not access_token:
            raise ValueError("access_token must not be empty")

        now = datetime.now(timezone.utc)
        if expires_at is None:
            # Default: 24 hours from now.  Using a simple +24h offset
            # guarantees the expiry is always in the future regardless of
            # the current time.  The previous logic (setting to today's
            # 03:30 UTC) could produce an already-expired token when the
            # process ran after 03:30 UTC.
            from datetime import timedelta
            expires_at = now + timedelta(hours=24)

        payload = {
            "access_token": access_token,
            "expires_at": expires_at.isoformat(),
            "updated_at": now.isoformat(),
        }

        self._atomic_write(payload)
        self._cached = payload
        logger.debug("Upstox token saved successfully")

    def get_state(self) -> TokenState:
        """Return the current token lifecycle state."""
        state, _ = self._load_state()
        return state

    def get_expiry(self) -> datetime | None:
        """Return the token expiry datetime, or None."""
        _, data = self._load_state()
        expires_str = data.get("expires_at")
        if not expires_str:
            return None
        try:
            return datetime.fromisoformat(expires_str)
        except (ValueError, TypeError):
            return None

    def clear(self) -> None:
        """Remove the cached token.

        This does not affect the database, OAuth config, or application
        settings.  It only removes the persisted access token file.
        """
        try:
            if self._token_file.exists():
                self._token_file.unlink()
            # Also remove parent dir if empty
            if self._cache_dir.exists() and not any(self._cache_dir.iterdir()):
                self._cache_dir.rmdir()
        except OSError as e:
            logger.warning("Failed to clear token cache: %s", e)
        self._cached = None
        logger.debug("Upstox token cache cleared")

    def get_auth_required_message(self) -> str | None:
        """Return a user-facing message if authentication is required, else None."""
        state = self.get_state()
        if state == TokenState.NO_TOKEN:
            return "No Upstox access token found. Please authenticate through the web login."
        if state == TokenState.EXPIRED:
            return "Upstox access token is expired. Please authenticate through the web login."
        if state == TokenState.CORRUPTED:
            return "Upstox token cache is corrupted. Please re-authenticate through the web login."
        return None

    # ------------------------------------------------------------------
    # Internal: load state
    # ------------------------------------------------------------------

    def _load_state(self) -> tuple[TokenState, dict[str, Any]]:
        """Load and validate the persisted token.

        Returns (state, data_dict).  data_dict may be empty.
        """
        # Return cached state if available
        if self._cached is not None:
            return self._validate_data(self._cached)

        # Read from disk
        if not self._token_file.exists():
            return TokenState.NO_TOKEN, {}

        try:
            raw = self._token_file.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("Failed to read token cache: %s", e)
            return TokenState.NO_TOKEN, {}

        if not raw:
            return TokenState.NO_TOKEN, {}

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Token cache contains invalid JSON")
            return TokenState.CORRUPTED, {}

        if not isinstance(data, dict):
            logger.warning("Token cache is not a JSON object")
            return TokenState.CORRUPTED, {}

        state, validated = self._validate_data(data)
        if state != TokenState.CORRUPTED:
            self._cached = data
        return state, validated

    def _validate_data(self, data: dict[str, Any]) -> tuple[TokenState, dict[str, Any]]:
        """Validate a token data dict and return its state."""
        access_token = data.get("access_token")
        if not access_token or not isinstance(access_token, str):
            return TokenState.CORRUPTED, data

        expires_str = data.get("expires_at")
        if not expires_str:
            # No expiry info — treat as expiring soon (conservative)
            return TokenState.EXPIRING_SOON, data

        try:
            expires_at = datetime.fromisoformat(expires_str)
        except (ValueError, TypeError):
            return TokenState.CORRUPTED, data

        now = datetime.now(timezone.utc)
        buffer = timedelta(seconds=self._expiry_buffer)

        if now >= expires_at + buffer:
            return TokenState.EXPIRED, data

        if now >= expires_at - buffer:
            return TokenState.EXPIRING_SOON, data

        return TokenState.VALID, data

    # ------------------------------------------------------------------
    # Internal: atomic write
    # ------------------------------------------------------------------

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        """Atomically write the token file.

        Uses temp-file → flush → rename pattern to prevent corruption
        if the process is interrupted during write.
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        content = json.dumps(payload, indent=2, default=str)

        # Write to a temporary file in the same directory
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._cache_dir),
            prefix=".upstox_token_tmp_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                # Force flush to disk (best-effort on Windows)
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

            # Atomic rename (on same filesystem)
            os.replace(tmp_path, str(self._token_file))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
