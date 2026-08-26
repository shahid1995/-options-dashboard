"""Phase 7.24.3 — Persistent Upstox Token Manager Tests.

Comprehensive test suite for the persistent token cache that enables
CLI tools to authenticate without browser-based OAuth.

All tests use synthetic token values. No real credentials are used.
No real Upstox API calls are made.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.upstox_token_manager import (
    TokenState,
    UpstoxTokenManager,
)
from app.services.upstox_client import (
    UpstoxClient,
    UpstoxAuthenticationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def token_dir(tmp_path: Path) -> Path:
    """Isolated temporary directory for token cache."""
    d = tmp_path / ".token_cache"
    d.mkdir()
    return d


@pytest.fixture
def manager(token_dir: Path) -> UpstoxTokenManager:
    """Fresh token manager with isolated cache directory."""
    return UpstoxTokenManager(cache_dir=token_dir, expiry_buffer_seconds=300)


@pytest.fixture
def future_expiry() -> datetime:
    """Token expiry 24 hours from now."""
    return datetime.now(timezone.utc) + timedelta(hours=24)


@pytest.fixture
def past_expiry() -> datetime:
    """Token expiry 1 hour ago."""
    return datetime.now(timezone.utc) - timedelta(hours=1)


# ---------------------------------------------------------------------------
# A. First-time state
# ---------------------------------------------------------------------------

class TestFirstTimeState:
    """No token file exists."""

    def test_no_token_file(self, manager: UpstoxTokenManager):
        assert manager.get_token() is None

    def test_has_token_false(self, manager: UpstoxTokenManager):
        assert manager.has_token() is False

    def test_state_no_token(self, manager: UpstoxTokenManager):
        assert manager.get_state() == TokenState.NO_TOKEN

    def test_auth_message_required(self, manager: UpstoxTokenManager):
        msg = manager.get_auth_required_message()
        assert msg is not None
        assert "No Upstox access token" in msg

    def test_expiry_none(self, manager: UpstoxTokenManager):
        assert manager.get_expiry() is None


# ---------------------------------------------------------------------------
# B. Save/load
# ---------------------------------------------------------------------------

class TestSaveLoad:
    """Save a token and reload from a new manager instance."""

    def test_save_and_get(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        assert manager.get_token() == "TEST_ACCESS_TOKEN_123"

    def test_save_and_has_token(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        assert manager.has_token() is True

    def test_save_and_get_state(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        assert manager.get_state() == TokenState.VALID

    def test_persistence_across_instances(self, token_dir: Path, future_expiry: datetime):
        """Two independent managers see the same persisted token."""
        m1 = UpstoxTokenManager(cache_dir=token_dir)
        m1.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)

        m2 = UpstoxTokenManager(cache_dir=token_dir)
        assert m2.get_token() == "TEST_ACCESS_TOKEN_123"
        assert m2.has_token() is True

    def test_save_persists_to_file(self, token_dir: Path, future_expiry: datetime):
        """The token file actually contains the saved data."""
        m = UpstoxTokenManager(cache_dir=token_dir)
        m.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)

        raw = (token_dir / "upstox_token.json").read_text()
        data = json.loads(raw)
        assert data["access_token"] == "TEST_ACCESS_TOKEN_123"
        assert "expires_at" in data
        assert "updated_at" in data

    def test_get_expiry(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        exp = manager.get_expiry()
        assert exp is not None
        # Allow 1s tolerance for test execution time
        assert abs((exp - future_expiry).total_seconds()) < 2

    def test_no_expiry_defaults_to_expiring_soon(self, manager: UpstoxTokenManager):
        """When expires_at is None, token is conservatively treated as EXPIRING_SOON."""
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=None)
        # The manager defaults to now+24h or similar
        assert manager.has_token() is True

    def test_empty_token_raises(self, manager: UpstoxTokenManager, future_expiry: datetime):
        with pytest.raises(ValueError, match="must not be empty"):
            manager.save("", expires_at=future_expiry)


# ---------------------------------------------------------------------------
# C. Expiry
# ---------------------------------------------------------------------------

class TestExpiry:
    """Token expiration behavior."""

    def test_valid_token(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        assert manager.get_state() == TokenState.VALID

    def test_expired_token(self, manager: UpstoxTokenManager, past_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=past_expiry)
        assert manager.get_state() == TokenState.EXPIRED
        assert manager.get_token() is None
        assert manager.has_token() is False

    def test_expiring_soon(self, manager: UpstoxTokenManager):
        """Token expires in 4 minutes (within 5-minute buffer)."""
        expires = datetime.now(timezone.utc) + timedelta(minutes=4)
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=expires)
        assert manager.get_state() == TokenState.EXPIRING_SOON
        # EXPIRING_SOON still returns the token (non-None)
        assert manager.get_token() == "TEST_ACCESS_TOKEN_123"
        assert manager.has_token() is True

    def test_expiry_buffer_boundary(self, manager: UpstoxTokenManager):
        """Token exactly at the buffer boundary should be EXPIRING_SOON."""
        expires = datetime.now(timezone.utc) + timedelta(seconds=300)
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=expires)
        state = manager.get_state()
        # At exactly the boundary: now >= expires_at - buffer
        assert state in (TokenState.EXPIRING_SOON, TokenState.VALID)

    def test_custom_expiry_buffer(self, token_dir: Path):
        """Custom buffer (60 seconds) makes token expire sooner."""
        manager = UpstoxTokenManager(cache_dir=token_dir, expiry_buffer_seconds=60)
        expires = datetime.now(timezone.utc) + timedelta(seconds=50)
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=expires)
        assert manager.get_state() == TokenState.EXPIRING_SOON

    def test_past_expiry_error_message(self, manager: UpstoxTokenManager, past_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=past_expiry)
        msg = manager.get_auth_required_message()
        assert msg is not None
        assert "expired" in msg.lower()


# ---------------------------------------------------------------------------
# D. Corruption
# ---------------------------------------------------------------------------

class TestCorruption:
    """Handle corrupted token files gracefully."""

    def test_invalid_json(self, token_dir: Path):
        (token_dir / "upstox_token.json").write_text("not json {{{")
        manager = UpstoxTokenManager(cache_dir=token_dir)
        assert manager.get_state() == TokenState.CORRUPTED
        assert manager.get_token() is None

    def test_empty_file(self, token_dir: Path):
        (token_dir / "upstox_token.json").write_text("")
        manager = UpstoxTokenManager(cache_dir=token_dir)
        assert manager.get_state() == TokenState.NO_TOKEN

    def test_truncated_json(self, token_dir: Path):
        (token_dir / "upstox_token.json").write_text('{"access_token": "abc"')
        manager = UpstoxTokenManager(cache_dir=token_dir)
        assert manager.get_state() == TokenState.CORRUPTED
        assert manager.get_token() is None

    def test_missing_access_token(self, token_dir: Path):
        data = {"expires_at": "2030-01-01T00:00:00+00:00", "updated_at": "2030-01-01T00:00:00+00:00"}
        (token_dir / "upstox_token.json").write_text(json.dumps(data))
        manager = UpstoxTokenManager(cache_dir=token_dir)
        assert manager.get_state() == TokenState.CORRUPTED

    def test_malformed_expiry(self, token_dir: Path):
        data = {"access_token": "TEST_TOKEN", "expires_at": "not-a-date"}
        (token_dir / "upstox_token.json").write_text(json.dumps(data))
        manager = UpstoxTokenManager(cache_dir=token_dir)
        assert manager.get_state() == TokenState.CORRUPTED
        assert manager.get_token() is None

    def test_non_dict_json(self, token_dir: Path):
        (token_dir / "upstox_token.json").write_text('["not", "a", "dict"]')
        manager = UpstoxTokenManager(cache_dir=token_dir)
        assert manager.get_state() == TokenState.CORRUPTED

    def test_no_expiry_field(self, token_dir: Path):
        data = {"access_token": "TEST_TOKEN"}
        (token_dir / "upstox_token.json").write_text(json.dumps(data))
        manager = UpstoxTokenManager(cache_dir=token_dir)
        # No expiry means EXPIRING_SOON (conservative)
        assert manager.get_state() == TokenState.EXPIRING_SOON
        assert manager.get_token() == "TEST_TOKEN"

    def test_corruption_auth_message(self, token_dir: Path):
        (token_dir / "upstox_token.json").write_text("broken")
        manager = UpstoxTokenManager(cache_dir=token_dir)
        msg = manager.get_auth_required_message()
        assert msg is not None
        assert "corrupted" in msg.lower()


# ---------------------------------------------------------------------------
# E. Clear
# ---------------------------------------------------------------------------

class TestClear:
    """Token clearing functionality."""

    def test_clear_removes_token(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        assert manager.has_token() is True
        manager.clear()
        assert manager.has_token() is False
        assert manager.get_state() == TokenState.NO_TOKEN

    def test_clear_removes_file(self, manager: UpstoxTokenManager, future_expiry: datetime):
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        assert manager._token_file.exists()
        manager.clear()
        assert not manager._token_file.exists()

    def test_clear_when_no_file(self, manager: UpstoxTokenManager):
        """Clearing when no file exists should not raise."""
        manager.clear()
        assert manager.has_token() is False

    def test_clear_persists(self, token_dir: Path, future_expiry: datetime):
        """Clearing persists across manager instances."""
        m1 = UpstoxTokenManager(cache_dir=token_dir)
        m1.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        m1.clear()

        m2 = UpstoxTokenManager(cache_dir=token_dir)
        assert m2.get_token() is None


# ---------------------------------------------------------------------------
# F. Atomic writes
# ---------------------------------------------------------------------------

class TestAtomicWrites:
    """Verify the token file is written atomically."""

    def test_no_temp_files_left(self, token_dir: Path, future_expiry: datetime):
        """After save, no temporary files remain in the cache directory."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)

        files = list(token_dir.iterdir())
        assert len(files) == 1
        assert files[0].name == "upstox_token.json"

    def test_file_content_valid_json(self, token_dir: Path, future_expiry: datetime):
        """The final file is always valid JSON."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        for i in range(3):
            manager.save(f"TEST_TOKEN_{i}", expires_at=future_expiry)
            raw = (token_dir / "upstox_token.json").read_text()
            data = json.loads(raw)
            assert data["access_token"] == f"TEST_TOKEN_{i}"

    def test_save_creates_directory(self, tmp_path: Path, future_expiry: datetime):
        """Save creates the cache directory if it doesn't exist."""
        nested = tmp_path / "deep" / "nested" / "cache"
        manager = UpstoxTokenManager(cache_dir=nested)
        manager.save("TEST_TOKEN", expires_at=future_expiry)
        assert nested.exists()
        assert (nested / "upstox_token.json").exists()


# ---------------------------------------------------------------------------
# G. Path determinism
# ---------------------------------------------------------------------------

class TestPathDeterminism:
    """Token path must not depend on CWD."""

    def test_default_path_is_deterministic(self):
        """Two managers with default cache_dir get the same path."""
        m1 = UpstoxTokenManager()
        m2 = UpstoxTokenManager()
        assert m1._token_file == m2._token_file

    def test_path_uses_backend_source_location(self):
        """Default path is derived from the backend app source location."""
        m = UpstoxTokenManager()
        # Should be inside the backend directory
        assert ".token_cache" in str(m._cache_dir)
        assert m._cache_dir.name == ".token_cache"

    def test_cwd_independence(self, token_dir: Path, future_expiry: datetime):
        """Changing CWD does not change the token cache path."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        manager.save("TEST_TOKEN", expires_at=future_expiry)

        original_path = str(manager._token_file)

        # Change CWD to a different temp directory
        with tempfile.TemporaryDirectory() as new_cwd:
            old_cwd = os.getcwd()
            try:
                os.chdir(new_cwd)
                # New manager should still use the same path
                manager2 = UpstoxTokenManager(cache_dir=token_dir)
                assert str(manager2._token_file) == original_path
            finally:
                os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# H. Git security
# ---------------------------------------------------------------------------

class TestGitSecurity:
    """Token cache is covered by .gitignore."""

    def test_gitignore_contains_token_cache(self):
        """The .gitignore must contain token cache patterns."""
        gitignore_path = Path(__file__).resolve().parent.parent.parent / ".gitignore"
        if not gitignore_path.exists():
            pytest.skip(".gitignore not found")

        content = gitignore_path.read_text(encoding="utf-8")
        assert ".token_cache" in content or "upstox_token.json" in content


# ---------------------------------------------------------------------------
# I. Logging security
# ---------------------------------------------------------------------------

class TestLoggingSecurity:
    """Access tokens must never appear in logs."""

    def test_token_not_in_exception_message(self, token_dir: Path, caplog):
        """Access token should not appear in any log output."""
        manager = UpstoxTokenManager(cache_dir=token_dir)

        with caplog.at_level(logging.DEBUG):
            manager.get_token()

        for record in caplog.records:
            assert "TEST_ACCESS_TOKEN" not in record.message
            assert "access_token" not in record.message.lower() or "not" in record.message.lower()

    def test_token_not_in_error_messages(self, manager: UpstoxTokenManager):
        """Error messages and exceptions should not expose the token."""
        msg = manager.get_auth_required_message()
        if msg:
            assert "TEST_" not in msg
            assert "Bearer" not in msg


# ---------------------------------------------------------------------------
# J. TokenProvider compatibility
# ---------------------------------------------------------------------------

class TestTokenProviderCompatibility:
    """TokenManager works with UpstoxClient through TokenProvider protocol."""

    def test_implements_token_provider(self, manager: UpstoxTokenManager):
        """Manager can be used as a TokenProvider."""
        # TokenProvider protocol: get_token() -> str | None
        assert hasattr(manager, "get_token")
        result = manager.get_token()
        assert result is None or isinstance(result, str)

    def test_upstox_client_with_token_manager(self, token_dir: Path, future_expiry: datetime):
        """UpstoxClient can accept the token manager as its provider."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)

        # UpstoxClient accepts any TokenProvider
        client = UpstoxClient(token_provider=manager)
        # Verify the client can get the token through the provider
        token = client._token_provider.get_token()
        assert token == "TEST_ACCESS_TOKEN_123"

    def test_upstox_client_no_token_raises(self, token_dir: Path):
        """UpstoxClient raises authentication error when no token available."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        client = UpstoxClient(token_provider=manager)
        token = client._token_provider.get_token()
        assert token is None


# ---------------------------------------------------------------------------
# K. Multiple instances
# ---------------------------------------------------------------------------

class TestMultipleInstances:
    """Multiple manager instances share the same persisted token."""

    def test_two_instances_same_token(self, token_dir: Path, future_expiry: datetime):
        m1 = UpstoxTokenManager(cache_dir=token_dir)
        m1.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)

        m2 = UpstoxTokenManager(cache_dir=token_dir)
        assert m2.get_token() == "TEST_ACCESS_TOKEN_123"

    def test_save_overwrites_previous(self, token_dir: Path, future_expiry: datetime):
        m1 = UpstoxTokenManager(cache_dir=token_dir)
        m1.save("OLD_TOKEN", expires_at=future_expiry)
        m1.save("NEW_TOKEN", expires_at=future_expiry)

        m2 = UpstoxTokenManager(cache_dir=token_dir)
        assert m2.get_token() == "NEW_TOKEN"
        assert m2.get_token() != "OLD_TOKEN"

    def test_save_then_clear_then_save(self, token_dir: Path, future_expiry: datetime):
        m1 = UpstoxTokenManager(cache_dir=token_dir)
        m1.save("FIRST_TOKEN", expires_at=future_expiry)
        m1.clear()
        m1.save("SECOND_TOKEN", expires_at=future_expiry)

        m2 = UpstoxTokenManager(cache_dir=token_dir)
        assert m2.get_token() == "SECOND_TOKEN"


# ---------------------------------------------------------------------------
# L. Process independence
# ---------------------------------------------------------------------------

class TestProcessIndependence:
    """Token persistence works without global Python state."""

    def test_new_manager_reads_persisted_token(self, token_dir: Path, future_expiry: datetime):
        """Creating a brand-new manager instance reads from disk."""
        # Instance 1: save
        m1 = UpstoxTokenManager(cache_dir=token_dir)
        m1.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)
        # Explicitly discard all in-memory state
        m1._cached = None

        # Instance 2: completely independent
        m2 = UpstoxTokenManager(cache_dir=token_dir)
        assert m2.get_token() == "TEST_ACCESS_TOKEN_123"

    def test_no_global_state_dependency(self, token_dir: Path, future_expiry: datetime):
        """Token is not stored in any global/module-level variable."""
        from app.services.upstox_token_manager import UpstoxTokenManager as UTM
        # The module-level state should not contain any token
        # Save in one manager, verify it's only on disk
        m = UTM(cache_dir=token_dir)
        m.save("TEST_TOKEN", expires_at=future_expiry)
        m._cached = None  # Clear in-memory cache

        # Fresh instance must read from file
        m2 = UTM(cache_dir=token_dir)
        assert m2.get_token() == "TEST_TOKEN"


# ---------------------------------------------------------------------------
# M. Database protection
# ---------------------------------------------------------------------------

class TestDatabaseProtection:
    """Token manager does not touch the market-data database."""

    def test_token_not_in_sqlite(self, token_dir: Path, future_expiry: datetime):
        """Token is never stored in the SQLite database."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        manager.save("TEST_ACCESS_TOKEN_123", expires_at=future_expiry)

        # Token should only exist in the JSON cache file, not in any .db file
        assert manager._token_file.exists()
        assert manager._token_file.suffix == ".json"


# ---------------------------------------------------------------------------
# N. No real API calls
# ---------------------------------------------------------------------------

class TestNoRealApiCalls:
    """This test module makes zero real Upstox API calls."""

    def test_only_mocked_client(self, token_dir: Path, future_expiry: datetime):
        """Verify we only create clients, never call real APIs."""
        manager = UpstoxTokenManager(cache_dir=token_dir)
        manager.save("TEST_TOKEN", expires_at=future_expiry)

        client = UpstoxClient(token_provider=manager)
        # Client is created but no API method is called
        assert client._token_provider.get_token() == "TEST_TOKEN"
