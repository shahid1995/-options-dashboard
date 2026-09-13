"""Environment and safety constants for the live staging smoke suite.

Secret-handling rules (enforced here, verified by review):
* Nothing derived from the CRDB DSN is ever printed, logged, or embedded
  in assertions. The DSN is read from the environment or a local,
  user-only file and used only to open a connection.
* Synthetic credentials are generated at runtime with `secrets` and live
  only in test memory.
* Session IDs are masked before any pytest output may contain them.
"""

import os
import secrets
import string
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Guard: this suite must be opted in explicitly so a plain `pytest` run of
# the backend test suite never contacts the live staging service.
# ---------------------------------------------------------------------------
def pytest_collection_modifyitems(config, items):
    if os.environ.get("STAGING_SMOKE"):
        return
    skip = pytest.mark.skip(reason="live staging suite; run with STAGING_SMOKE=1")
    for item in items:
        if "staging_smoke" in str(item.fspath):
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Targets (overridable via environment; defaults are the public staging URLs)
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get(
    "STAGING_API_URL", "https://strikenova-api-staging.onrender.com"
).rstrip("/")
FRONTEND_URL = os.environ.get(
    "STAGING_FRONTEND_URL", "https://strikenova-frontend-staging.vercel.app"
).rstrip("/")
UNRELATED_ORIGIN = "https://unrelated-origin.example.com"

# Render free tier can sleep; allow a generous per-request timeout.
HTTP_TIMEOUT = 45.0

# Local-only CRDB DSN file written by earlier staging deployment sessions
# (documented in docs/architecture/RENDER_STAGING_DEPLOYMENT.md).
CRDB_DSN_FILE = Path(
    os.environ.get("STAGING_CRDB_DSN_FILE", "~/.strikenova_staging_crdb.txt")
).expanduser()


# ---------------------------------------------------------------------------
# Runtime synthetic credentials (never persisted, never printed)
# ---------------------------------------------------------------------------
_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_"


def generate_test_email() -> str:
    """Unique synthetic identity for a single smoke run."""
    return f"smoke-{secrets.token_hex(6)}@smoke.example.com"


def generate_test_password() -> str:
    """Runtime-generated synthetic password (lives only in test memory)."""
    rng = secrets.SystemRandom()
    return "".join(rng.choice(_PASSWORD_ALPHABET) for _ in range(20))


def mask(value: str | None) -> str:
    """Mask a session id for safe output: prefix + length, never the value."""
    if not value:
        return "<none>"
    return f"{value[:6]}... (len={len(value)})"


@pytest.fixture(scope="session")
def crdb_dsn() -> str:
    """Return a full staging CRDB DSN, or skip.

    Accepted sources, in order:
    1. ``STAGING_CRDB_DSN`` environment variable (a full ``postgres://`` DSN)
    2. the local-only credential file, IF it contains a full URL-style DSN

    The legacy local file stores ``<dbname>:<password>`` (not a DSN); that
    format cannot be turned into a connection here because host and user
    are not known, and nothing from the file is ever printed. When no
    usable DSN is available the direct-CRDB checks skip — the DB-backed
    path is still proven live by the authenticated ``/paper/capital`` HTTP
    test.
    """
    env_dsn = os.environ.get("STAGING_CRDB_DSN", "").strip()
    if env_dsn:
        return env_dsn
    if CRDB_DSN_FILE.exists():
        content = CRDB_DSN_FILE.read_text(encoding="utf-8").strip()
        if content.startswith(("postgres://", "postgresql://")):
            return content
    pytest.skip(
        "no usable staging CRDB DSN (set STAGING_CRDB_DSN or put a full "
        "postgres:// DSN in the local credential file); the DB-backed path "
        "remains covered by the /paper/capital HTTP test"
    )
