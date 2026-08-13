import os

os.environ.setdefault("UPSTOX_API_KEY", "test-api-key")
os.environ.setdefault("UPSTOX_API_SECRET", "test-api-secret")
os.environ.setdefault("UPSTOX_REDIRECT_URI", "http://localhost:8000/auth/callback")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")

import pytest

from app.services import token_store


@pytest.fixture(autouse=True)
def reset_token_store():
    token_store.clear_token()
    yield
    token_store.clear_token()
