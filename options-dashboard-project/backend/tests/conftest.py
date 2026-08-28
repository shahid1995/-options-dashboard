import os
import sys

os.environ.setdefault("UPSTOX_API_KEY", "test-api-key")
os.environ.setdefault("UPSTOX_API_SECRET", "test-api-secret")
os.environ.setdefault("UPSTOX_REDIRECT_URI", "http://localhost:8000/auth/callback")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

import pytest

from app.services import token_store


# ---------------------------------------------------------------------------
# Production database protection (Phase 7.8C)
# ---------------------------------------------------------------------------
#
# During test execution, override the production SQLAlchemy engine and
# SessionLocal with in-memory equivalents so that no test (or fixture,
# or init_db() triggered by TestClient startup) can accidentally write
# to backend/paper_journal.db.
#
# The production module-level `engine` and `SessionLocal` are replaced
# once at import time.  Tests that explicitly create their own engine
# (StaticPool / sqlite://) are unaffected.
# ---------------------------------------------------------------------------

if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.db as _db_module

    _test_engine = _create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _db_module.engine = _test_engine
    _db_module.SessionLocal = _sessionmaker(
        bind=_test_engine, autocommit=False, autoflush=False
    )


@pytest.fixture(autouse=True)
def reset_token_store():
    token_store.clear_token()
    yield
    token_store.clear_token()

