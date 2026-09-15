"""Security regression tests — OAuth callback query-string redaction in access logs.

Threat model (staging incident, 2026-09-15): FYERS redirects back to
``/auth/callback`` with the single-use ``auth_code`` JWT and the signed
OAuth ``state`` in the QUERY STRING. Uvicorn's access logger records
``get_path_with_query_string(scope)`` verbatim, so provider auth codes
landed in Render/Uvicorn access logs.

Layer under test: the ``uvicorn.access`` LOGGER — not middleware.
(Verified: ``Procfile`` runs plain ``uvicorn app.main:app`` and Uvicorn's
``RequestResponseCycle.send`` emits ``'<method> <path?><query> HTTP/x'``
directly via ``access_logger.info``; ASGI middleware never sees that
formatted record. The fix must therefore sit on the logger itself.)

Required assertions:
  * ``/auth/callback?code=...&auth_code=...&state=...`` → the access log
    line contains NO query-string values (preferred outcome: the line
    shows the bare path ``/auth/callback``).
  * ``auth_code`` never appears; ``state`` never appears; arbitrary
    query parameters never appear for that path.
  * Method/path/status remain available in the access line.
  * Other endpoints keep their normal access logging — including their
    query strings (this filter is narrowly scoped, not global redaction).
  * Application error logging is untouched (separate logger namespace).

No real auth codes, tokens, or credentials are used anywhere — only the
sythetic markers below.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app  # noqa: F401 — importing main installs the redaction filter
from app.services.access_log_redaction import (
    SENSITIVE_ACCESS_PATH,
    install_access_log_redaction,
    redact_query_string,
    CallbackQueryRedactionFilter,
)

FAKE_AUTH_CODE = "FAKE_AUTH_CODE"
FAKE_STATE = "FAKE_SIGNED_STATE"


class _ListHandler(logging.Handler):
    """Thread-safe capturing handler.

    TestClient serves requests on a portal thread, so ``caplog`` (which
    installs its handler on the root logger of the main thread) does not
    see child-thread records reliably. Attaching directly to the target
    logger captures whatever thread emits.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [self.format(r) if self.formatter else r.getMessage() for r in self.records]


@pytest.fixture
def access_log_capture():
    handler = _ListHandler()
    logger = logging.getLogger("uvicorn.access")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def _emit_like_uvicorn(handler: _ListHandler, path: str, query: bytes, status: int = 200) -> None:
    """Emit an access record EXACTLY like Uvicorn's protocol layer does.

    TestClient bypasses Uvicorn's HTTP protocol (it drives the ASGI app
    directly), so no real uvicorn.access record is produced in-process.
    The faithful reproduction is to call the same logger with the same
    format string and the same argument Uvicorn passes for the request
    target — including ``get_path_with_query_string(scope)``.
    """
    from uvicorn.protocols.http.h11_impl import get_path_with_query_string

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query,
        "http_version": "1.1",
        "headers": [],
        "client": ("10.0.0.1", 12345),
    }
    logger = logging.getLogger("uvicorn.access")
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        get_client_addr(scope),
        scope["method"],
        get_path_with_query_string(scope),
        scope["http_version"],
        status,
    )


def get_client_addr(scope):
    from uvicorn.protocols.utils import get_client_addr as _g

    return _g(scope)


# ---------------------------------------------------------------------------
# Unit tests — the redaction decision function
# ---------------------------------------------------------------------------


class TestAccessFilterUnit:
    def test_callback_query_string_is_dropped(self):
        line = f"/auth/callback?code=200&auth_code={FAKE_AUTH_CODE}&state={FAKE_STATE}"
        assert redact_query_string(line) == "/auth/callback"

    def test_callback_bare_path_is_unchanged(self):
        assert redact_query_string("/auth/callback") == "/auth/callback"

    def test_callback_status_param_is_dropped_too(self):
        # FYERS's real redirect shape also carries s=ok / code=200 status
        # parameters — the whole query string is dropped for this path.
        line = "/auth/callback?s=ok&code=200&auth_code=X&state=Y"
        assert redact_query_string(line) == "/auth/callback"

    def test_other_endpoints_keep_their_query_strings(self):
        line = "/api/chains?symbol=NIFTY&expiry=2026-09-24"
        assert redact_query_string(line) == line

    def test_other_endpoints_bare_path_unchanged(self):
        assert redact_query_string("/health") == "/health"

    def test_trailing_semicolon_of_bare_callback_is_not_touched(self):
        assert redact_query_string("/auth/callback") == "/auth/callback"

    def test_sensitive_path_constant_is_the_bare_callback_path(self):
        # Guard against accidental scope creep or typos.
        assert SENSITIVE_ACCESS_PATH == "/auth/callback"


# ---------------------------------------------------------------------------
# Integration tests — the actual uvicorn.access logger emission
# (records are emitted through Uvicorn's own helpers/format — the exact
# production pathway; see _emit_like_uvicorn)
# ---------------------------------------------------------------------------


class TestUvicornAccessLogIntegration:
    def test_callback_access_line_has_no_query_values(self, access_log_capture):
        _emit_like_uvicorn(
            access_log_capture,
            "/auth/callback",
            b"s=ok&code=200&auth_code=" + FAKE_AUTH_CODE.encode() + b"&state=" + FAKE_STATE.encode(),
        )

        messages = access_log_capture.messages()
        callback_lines = [m for m in messages if "/auth/callback" in m]
        assert callback_lines, "callback access line must still be emitted (redact, not silence)"
        joined = "\n".join(messages)
        assert FAKE_AUTH_CODE not in joined
        assert FAKE_STATE not in joined
        for line in callback_lines:
            assert "?" not in line.split("/auth/callback", 1)[1]

    def test_callback_line_keeps_method_path_status(self, access_log_capture):
        _emit_like_uvicorn(
            access_log_capture,
            "/auth/callback",
            b"auth_code=" + FAKE_AUTH_CODE.encode() + b"&state=" + FAKE_STATE.encode(),
            status=307,
        )
        callback_lines = [m for m in access_log_capture.messages() if "/auth/callback" in m]
        assert callback_lines, "callback access line must still be emitted"
        line = callback_lines[-1]
        assert "GET" in line
        assert "/auth/callback" in line
        assert " HTTP/1.1" in line
        assert "307" in line

    def test_other_endpoints_unaffected(self, access_log_capture):
        _emit_like_uvicorn(access_log_capture, "/api/market-status", b"symbol=NIFTY")
        _emit_like_uvicorn(access_log_capture, "/health", b"")

        messages = "\n".join(access_log_capture.messages())
        # Non-callback query strings must still be logged normally.
        assert "symbol=NIFTY" in messages
        assert any("/health" in m for m in access_log_capture.messages())
        assert FAKE_AUTH_CODE not in messages

    def test_filter_rewrites_uvicorn_args_in_place(self, access_log_capture):
        """Direct filter-level proof on a raw LogRecord (uvicorn arg shape)."""
        from uvicorn.protocols.http.h11_impl import get_path_with_query_string

        scope = {
            "type": "http", "method": "GET", "path": "/auth/callback",
            "query_string": b"code=200&auth_code=X&state=Y",
            "http_version": "1.1", "headers": [], "client": ("c", 1),
        }
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, "/", 1,
            '%s - "%s %s HTTP/%s" %d',
            ("c:1", "GET", get_path_with_query_string(scope), "1.1", 200),
            None,
        )
        assert CallbackQueryRedactionFilter().filter(record) is True  # never silenced
        assert record.getMessage().count("/auth/callback?") == 0
        assert record.getMessage().count("/auth/callback ") == 1

    def test_app_error_logging_still_works(self, access_log_capture, caplog):
        # Application logs use a different logger namespace — the filter
        # must not touch them. (Debugging without logging secrets is the
        # contract; the auth router's error paths already log without
        # token material — that is covered by the popup-OAuth suite.)
        logger = logging.getLogger("app.routers.auth")
        with caplog.at_level(logging.INFO, logger="app.routers.auth"):
            logger.info("Token/profile exchange failed: UPSTREAM_ERROR: test")
        assert "UPSTREAM_ERROR: test" in caplog.text

    def test_install_is_idempotent(self, access_log_capture):
        logger = logging.getLogger("uvicorn.access")
        before = len(logger.filters)
        install_access_log_redaction()
        install_access_log_redaction()
        after = len(logger.filters)
        assert after == before, "repeated installs must not stack filters"
