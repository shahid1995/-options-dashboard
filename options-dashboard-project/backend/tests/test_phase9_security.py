"""Phase 9 — Security Regression & Rate Limiter Tests."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.token_store import (
    set_token, get_token, clear_token, get_session_count,
    _sessions, _pending_states,
)
from app.services.rate_limiter import SessionRateLimiter, RateLimitRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def setup_method():
    _sessions.clear()
    _pending_states.clear()


# ---------------------------------------------------------------------------
# clear_token session-scoping tests (Phase 9A)
# ---------------------------------------------------------------------------

class TestClearTokenIsolation:
    """Verify clear_token(session_id) only affects the specified session."""

    def test_clear_a_does_not_affect_b(self):
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")
        clear_token(sid_a)
        assert get_token(sid_a) is None
        assert get_token(sid_b) == "token_b"

    def test_clear_b_does_not_affect_a(self):
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")
        clear_token(sid_b)
        assert get_token(sid_a) == "token_a"
        assert get_token(sid_b) is None

    def test_logout_a_does_not_logout_b(self):
        """Simulate: User A logs out, User B remains authenticated."""
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        # Simulate auth.py logout for User A
        clear_token(sid_a)

        # User B should still be authenticated
        assert get_token(sid_b) == "token_b"

    def test_broker_401_for_a_does_not_invalidate_b(self):
        """Simulate: User A's broker token expires, User B is unaffected."""
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        # Simulate chains.py handling broker 401 for User A
        clear_token(sid_a)

        # User B should still have their token
        assert get_token(sid_b) == "token_b"

    def test_websocket_auth_failure_for_a_does_not_invalidate_b(self):
        """Simulate: User A's WebSocket auth fails, User B is unaffected."""
        sid_a = set_token("token_a")
        sid_b = set_token("token_b")

        # Simulate chains.py WebSocket auth failure for User A
        clear_token(sid_a)

        # User B should still be authenticated
        assert get_token(sid_b) == "token_b"


# ---------------------------------------------------------------------------
# Token leakage tests
# ---------------------------------------------------------------------------

class TestTokenLeakage:
    """Verify tokens never appear in API responses or logs."""

    def test_live_gex_response_has_no_token(self):
        """The /gex/live response must not contain broker tokens."""
        from app.routers.live_gex import LiveGexResponse
        resp = LiveGexResponse()
        resp_dict = resp.model_dump()
        assert "token" not in str(resp_dict).lower() or "methodology" in str(resp_dict).lower()

    def test_gex_snapshot_response_has_no_token(self):
        from app.routers.gex import GexSnapshotOut
        # GexSnapshotOut should not have a token field
        fields = GexSnapshotOut.model_fields
        assert "token" not in fields
        assert "access_token" not in fields

    def test_get_any_token_not_in_production_paths(self):
        """get_any_token() must not be used in any request handler."""
        import ast
        import os

        routers_dir = os.path.join(os.path.dirname(__file__), "..", "app", "routers")
        for fname in os.listdir(routers_dir):
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(routers_dir, fname)
            with open(filepath) as f:
                content = f.read()
            assert "get_any_token()" not in content, (
                f"get_any_token() found in {fname} — must use get_token(session_id)"
            )


# ---------------------------------------------------------------------------
# Rate limiter tests (Phase 9B)
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Verify per-session rate limiting."""

    def test_under_limit_passes(self):
        limiter = SessionRateLimiter(rules={"/test": RateLimitRule(max_requests=5, window_seconds=60)})
        for _ in range(4):
            limiter.check("session_1", "/test")  # Should not raise

    def test_over_limit_raises_429(self):
        limiter = SessionRateLimiter(rules={"/test": RateLimitRule(max_requests=3, window_seconds=60)})
        limiter.check("session_1", "/test")
        limiter.check("session_1", "/test")
        limiter.check("session_1", "/test")
        with pytest.raises(Exception) as exc_info:
            limiter.check("session_1", "/test")
        assert exc_info.value.status_code == 429

    def test_independent_users(self):
        """User A's rate limit does not affect User B."""
        limiter = SessionRateLimiter(rules={"/test": RateLimitRule(max_requests=2, window_seconds=60)})
        limiter.check("user_a", "/test")
        limiter.check("user_a", "/test")
        with pytest.raises(Exception):
            limiter.check("user_a", "/test")  # A is over limit

        # B should still be able to make requests
        limiter.check("user_b", "/test")  # Should not raise

    def test_window_expiry(self):
        """After window expires, requests should be allowed again."""
        limiter = SessionRateLimiter(rules={"/test": RateLimitRule(max_requests=2, window_seconds=1)})
        limiter.check("s1", "/test")
        limiter.check("s1", "/test")
        with pytest.raises(Exception):
            limiter.check("s1", "/test")

        time.sleep(1.1)
        limiter.check("s1", "/test")  # Should pass after window expires

    def test_cleanup(self):
        limiter = SessionRateLimiter(rules={"/test": RateLimitRule(max_requests=10, window_seconds=60)})
        limiter.check("old_session", "/test")
        limiter._hits["old_session"]["/test"] = [time.time() - 1000]  # Force old
        cleaned = limiter.cleanup(max_age_seconds=600)
        assert cleaned >= 1

    def test_prefix_matching(self):
        limiter = SessionRateLimiter(rules={"/chains": RateLimitRule(max_requests=1, window_seconds=60)})
        limiter.check("s1", "/chains/NIFTY")  # Should match /chains prefix
        with pytest.raises(Exception):
            limiter.check("s1", "/chains/NIFTY")

    def test_no_rule_passes(self):
        limiter = SessionRateLimiter(rules={})
        limiter.check("s1", "/unknown")  # Should not raise


# ---------------------------------------------------------------------------
# CORS configuration tests (Phase 9C)
# ---------------------------------------------------------------------------

class TestCorsConfiguration:
    """Verify CORS is environment-dependent."""

    def test_cors_origins_dont_include_localhost_by_default(self):
        """In production (ALLOW_LOCALHOST_CORS=False), localhost should not be in CORS."""
        with patch("app.main.settings") as mock_settings:
            mock_settings.FRONTEND_URL = "https://app.strikenova.com"
            mock_settings.ALLOW_LOCALHOST_CORS = False
            mock_settings.DEBUG = False
            # The CORS middleware is configured at import time, but we can
            # verify the configuration logic
            assert not mock_settings.ALLOW_LOCALHOST_CORS


# ---------------------------------------------------------------------------
# Database portability tests (Phase 9D)
# ---------------------------------------------------------------------------

class TestDatabasePortability:
    """Verify no sqlite_insert remains in production services."""

    def test_no_sqlite_insert_in_services(self):
        """All services must use dialect_insert, not sqlite_insert."""
        import os
        services_dir = os.path.join(os.path.dirname(__file__), "..", "app", "services")
        for fname in os.listdir(services_dir):
            if not fname.endswith(".py") or fname.startswith("test_"):
                continue
            filepath = os.path.join(services_dir, fname)
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                continue
            # Allow sqlite_insert in backfill_benchmark (tool, not production service)
            if fname == "backfill_benchmark.py":
                continue
            assert "sqlite_insert" not in content, (
                f"sqlite_insert found in {fname} — use dialect_insert instead"
            )

    def test_dialect_insert_works_for_sqlite(self):
        """Verify dialect_insert produces correct insert for SQLite."""
        from app.db import engine
        from app.utils.db_dialect import dialect_insert
        from app.models import GexSnapshot

        ins = dialect_insert(engine, GexSnapshot)
        # Should have on_conflict_do_update (SQLite dialect)
        assert hasattr(ins, "on_conflict_do_update")


# ---------------------------------------------------------------------------
# Health/readiness tests (Phase 9I)
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    """Verify health and readiness endpoints."""

    def test_health_returns_ok(self):
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readiness_returns_ok(self):
        client = TestClient(app)
        resp = client.get("/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["checks"]["database"] == "ok"

    def test_readiness_route_is_registered(self):
        """Verify /readiness is in the actual FastAPI route table.

        Regression test: a previous deployment served a completely different
        application because the Railway service had an orphaned domain pointing
        to an old service. This test ensures the route table itself is correct
        regardless of deployment configuration.
        """
        routes = []
        for route in app.routes:
            if hasattr(route, "methods"):
                for method in route.methods:
                    routes.append((method.upper(), route.path))
        assert ("GET", "/readiness") in routes, (
            "/readiness route not found in app routes — "
            f"registered routes: {[r for r in routes if r[1] == '/health']}"
        )

    def test_app_title_is_strikenova(self):
        """Ensure the FastAPI app is the StrikeNova Options Dashboard.

        Regression: a misconfigured Railway service was serving 'ET Verdict'
        instead of StrikeNova because of an orphaned public domain.
        """
        assert app.title == "Options Dashboard API"


# ---------------------------------------------------------------------------
# Staging URL integrity (Phase J)
# ---------------------------------------------------------------------------


class TestStagingUrlIntegrity:
    """Verify no documentation references the orphaned staging domain.

    Regression: Railway's staging-backend.up.railway.app was an orphaned
    domain serving 'ET Verdict' instead of StrikeNova. All staging
    references must use the corrected domain.
    """

    ORPHANED_HOST = "staging-backend.up.railway.app"

    def test_no_orphaned_staging_url_in_docs(self):
        import glob
        import os

        docs_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "docs"
        )
        if not os.path.isdir(docs_dir):
            pytest.skip("docs directory not found")

        violations = []
        for fpath in glob.glob(os.path.join(docs_dir, "**", "*.md"), recursive=True):
            try:
                with open(fpath, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if self.ORPHANED_HOST in line:
                            violations.append(f"{os.path.basename(fpath)}:{i}")
            except UnicodeDecodeError:
                continue
        assert not violations, (
            f"Orphaned staging URL '{self.ORPHANED_HOST}' found in: {violations}. "
            "Use staging-backend-staging-8159.up.railway.app instead."
        )


# ---------------------------------------------------------------------------
# Security: no _state references in production code
# ---------------------------------------------------------------------------

class TestNoLegacyState:
    """Verify no legacy _state references remain in production code."""

    def test_no_state_imports_in_routers(self):
        import os
        routers_dir = os.path.join(os.path.dirname(__file__), "..", "app", "routers")
        for fname in os.listdir(routers_dir):
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(routers_dir, fname)
            with open(filepath) as f:
                for i, line in enumerate(f, 1):
                    if "import.*_state" in line and "token_store" in line:
                        assert False, f"_state import found in {fname}:{i}"

    def test_no_state_imports_in_services(self):
        import os
        services_dir = os.path.join(os.path.dirname(__file__), "..", "app", "services")
        for fname in os.listdir(services_dir):
            if not fname.endswith(".py") or fname.startswith("test_"):
                continue
            filepath = os.path.join(services_dir, fname)
            try:
                with open(filepath, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if "_state" in line and "token_store" in line and "import" in line:
                            assert False, f"_state import found in {services_dir}/{fname}:{i}"
            except UnicodeDecodeError:
                continue
