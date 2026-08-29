"""CORS configuration regression tests.

Verifies that the FastAPI CORS middleware allows the HTTP methods
actually used by the frontend application (GET, POST, PUT, DELETE)
and rejects preflight requests from unrelated origins.

Phase 6.11: production deployment readiness — CORS blocker fix.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _preflight(client, origin, method, path="/health"):
    """Send an OPTIONS preflight request and return the response."""
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "Content-Type, X-Session-Id",
        },
    )


class TestCORSMethods:
    """Verify that all HTTP methods used by the frontend are permitted."""

    def test_get_preflight_accepted(self, client):
        resp = _preflight(client, settings.FRONTEND_URL, "GET")
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "GET" in allowed

    def test_post_preflight_accepted(self, client):
        resp = _preflight(client, settings.FRONTEND_URL, "POST")
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "POST" in allowed

    def test_put_preflight_accepted(self, client):
        """PUT is used for template updates (api.put in frontend)."""
        resp = _preflight(client, settings.FRONTEND_URL, "PUT")
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "PUT" in allowed

    def test_delete_preflight_accepted(self, client):
        """DELETE is used for template deletion (api.delete in frontend)."""
        resp = _preflight(client, settings.FRONTEND_URL, "DELETE")
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "DELETE" in allowed

    def test_options_preflight_accepted(self, client):
        resp = _preflight(client, settings.FRONTEND_URL, "OPTIONS")
        assert resp.status_code == 200


class TestCORSOrigins:
    """Verify that the configured frontend origin is accepted."""

    def test_configured_frontend_url_accepted(self, client):
        resp = _preflight(client, settings.FRONTEND_URL, "GET")
        # When origin is accepted, CORS headers are present
        assert "access-control-allow-origin" in resp.headers

    def test_localhost_accepted(self, client):
        resp = _preflight(client, "http://localhost:3000", "GET")
        assert "access-control-allow-origin" in resp.headers

    def test_unrelated_origin_rejected(self, client):
        """An origin not in the allow list must NOT get CORS headers."""
        resp = _preflight(client, "https://evil.example.com", "GET")
        # When origin is rejected, access-control-allow-origin is absent
        assert "access-control-allow-origin" not in resp.headers

    def test_credentials_allowed_for_configured_origin(self, client):
        resp = _preflight(client, settings.FRONTEND_URL, "POST")
        assert resp.headers.get("access-control-allow-credentials") == "true"


class TestCORSActualRequests:
    """Verify CORS works on actual GET/POST/PUT/DELETE requests."""

    def test_get_health_has_cors_headers(self, client):
        resp = client.get("/health", headers={"Origin": settings.FRONTEND_URL})
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    def test_post_has_cors_headers(self, client):
        resp = client.post(
            "/paper/portfolio/reset",
            headers={"Origin": settings.FRONTEND_URL, "X-Session-Id": "test"},
        )
        # May return 401 (no valid session) but CORS headers should be present
        assert "access-control-allow-origin" in resp.headers



class TestCORSCommaSeparatedOrigins:
    """Verify comma-separated FRONTEND_URL and ADDITIONAL_CORS_ORIGINS parsing."""

    def test_comma_separated_parsing_logic(self):
        """The CORS origin parser correctly splits comma-separated strings."""
        from app.main import _cors_origins
        # In test env, FRONTEND_URL is http://localhost:3000 and ADDITIONAL_CORS_ORIGINS is ""
        assert "http://localhost:3000" in _cors_origins

    def test_configured_origin_accepted(self, client):
        """The configured frontend URL is accepted."""
        resp = _preflight(client, settings.FRONTEND_URL, "POST")
        assert resp.status_code == 200

    def test_unrelated_origin_still_rejected(self, client):
        """Origins not in any allowed list are still rejected."""
        resp = _preflight(client, "https://evil.example.com", "GET")
        assert "access-control-allow-origin" not in resp.headers

    def test_additional_cors_origins_configurable(self):
        """ADDITIONAL_CORS_ORIGINS env var is read correctly."""
        assert hasattr(settings, "ADDITIONAL_CORS_ORIGINS")
        # In test env it defaults to empty string
        assert settings.ADDITIONAL_CORS_ORIGINS == ""

    def test_cors_origins_list_built_from_settings(self):
        """The _cors_origins list is built from FRONTEND_URL and ADDITIONAL_CORS_ORIGINS."""
        from app.main import _cors_origins
        assert isinstance(_cors_origins, list)
        assert len(_cors_origins) >= 1
        assert "http://localhost:3000" in _cors_origins


class TestFrontENDOriginProperty:
    """Verify FRONTEND_ORIGIN returns the first URL when comma-separated."""

    def test_single_url(self):
        from unittest.mock import patch
        with patch.object(settings, "FRONTEND_URL", "http://localhost:3000"):
            assert settings.FRONTEND_ORIGIN == "http://localhost:3000"

    def test_comma_separated_returns_first(self):
        from unittest.mock import patch
        with patch.object(settings, "FRONTEND_URL", "http://localhost:3000,https://preview.vercel.app"):
            assert settings.FRONTEND_ORIGIN == "http://localhost:3000"

    def test_strips_whitespace(self):
        from unittest.mock import patch
        with patch.object(settings, "FRONTEND_URL", "  http://localhost:3000 , https://preview.vercel.app  "):
            assert settings.FRONTEND_ORIGIN == "http://localhost:3000"
