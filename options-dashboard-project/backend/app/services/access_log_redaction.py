"""Access-log redaction for OAuth callback query strings (security hardening).

Incident (staging, 2026-09-15): FYERS redirects to
``/auth/callback?...&auth_code=<single-use JWT>&state=<signed>`` and
Uvicorn's access logger records the full request target
(``get_path_with_query_string(scope)``) verbatim — provider auth codes
and signed OAuth state landed in Uvicorn/Render access logs.

WHY A LOGGER FILTER (not middleware, not global log suppression):

  * The emitting layer is Uvicorn's HTTP protocol code
    (``RequestResponseCycle.send`` → ``access_logger.info(...)``) —
    it runs OUTSIDE the ASGI stack, so ASGI middleware never sees the
    record.
  * Disabling access logging globally would destroy operational
    visibility for every other endpoint.
  * ``logging.Filter`` runs BEFORE formatting, and Uvicorn passes the
    request target as ``args[2]`` of a fixed five-argument format
    (``'%s - "%s %s HTTP/%s" %d'``). Rewriting that single argument for
    one path is the narrowest possible intervention.

SCOPE: only the exact sensitive path (``/auth/callback``) has its query
string dropped; the line itself (method, path, HTTP version, status)
is preserved, and every other endpoint keeps full normal access
logging. The filter NEVER returns False (it never silences a record)
and never touches application loggers.

Failure behavior is fail-closed-on-values, fail-open-on-logging: if
argument-shape inspection fails for an unexpected record shape, the
filter leaves the record untouched (an unredacted line is worse than a
malformed one only in the sense that correctness beats availability
here — hence the conservative "only rewrite when we positively
recognize the shape" policy).

Install once at app import (``app.main``); installation is idempotent.
"""

from __future__ import annotations

import logging

# The exact path whose query string must never be logged. Bare-path
# comparison (no prefix matching) keeps the filter from ever touching
# /auth/login, /auth/status, /auth/callback-similar paths, etc.
SENSITIVE_ACCESS_PATH = "/auth/callback"

_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'
_TARGET_ARG_INDEX = 2  # (client_addr, method, REQUEST_TARGET, http_version, status)


def redact_query_string(path_with_query: str) -> str:
    """Return the access-log-safe request target for a given path(+query).

    - Sensitive path → bare path (query string dropped entirely).
    - Any other path → returned unchanged.
    """
    if not path_with_query:
        return path_with_query
    target = path_with_query
    # Split off the query component; match the path exactly.
    path = target.split("?", 1)[0].split(";", 1)[0]
    if path == SENSITIVE_ACCESS_PATH:
        return SENSITIVE_ACCESS_PATH
    return target


class CallbackQueryRedactionFilter(logging.Filter):
    """Rewrite Uvicorn access records for the sensitive path pre-format.

    Uvicorn emits: ``access_logger.info(_ACCESS_FORMAT, client, method,
    path_with_query, http_version, status)``. This filter replaces
    ``args[_TARGET_ARG_INDEX]`` with the redacted request target when
    (and only when) the record comes from the access logger with the
    expected format/argument shape and the request targets the
    sensitive path. All other records pass through untouched; the
    filter always returns True.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if (
                args
                and isinstance(args, tuple)
                and len(args) == 5
                and record.getMessage() == _ACCESS_FORMAT % (args)  # cheap shape check
            ):
                target = args[_TARGET_ARG_INDEX]
                if isinstance(target, str):
                    redacted = redact_query_string(target)
                    if redacted != target:
                        new_args = list(args)
                        new_args[_TARGET_ARG_INDEX] = redacted
                        record.args = tuple(new_args)
            # Never silence: this filter only rewrites, never drops.
            return True
        except Exception:  # pragma: no cover — never break the access log
            return True


def install_access_log_redaction() -> bool:
    """Attach the redaction filter to the ``uvicorn.access`` logger.

    Idempotent (guarded by filter class identity). Returns True if the
    filter was newly installed. Import side effect of ``app.main``.
    """
    logger = logging.getLogger("uvicorn.access")
    for existing in logger.filters:
        if isinstance(existing, CallbackQueryRedactionFilter):
            return False
    logger.addFilter(CallbackQueryRedactionFilter())
    return True


# Install on import so the filter exists before Uvicorn serves anything,
# including under ``uvicorn app.main:app`` where module import happens on
# the server's import hook.
install_access_log_redaction()
