"""Tests for the masked FYERS staging-diagnostics endpoint.

Contract under test (GET /fyers/diagnostics):

* 404 for users without a FYERS connection — no cross-user enumeration;
* the caller can only ever reach their OWN connection;
* identity is reported MASKED with its field name — never the raw value;
* no credential material (token/secret/app id/appIdHash) ever appears;
* broker failures map to canonical BrokerErrorCode names;
* the response reports the read-only probes (funds/positions/holdings/
  tradebook/quote/option contracts) — never an order endpoint.

All broker payloads are synthetic; the FYERS adapter seams are mocked per
the repository's established technique (test_identity_linking.py).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.db import SessionLocal as _real_session_local
import app.routers.auth as auth_mod
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.identity import (
    BrokerConnection,
    BrokerToken,
    User,
    create_session_record,
)
from app.identity import store_credentials
from app.main import app
from app.services import token_store

FYERS_APP_ID = "SPSYNTH01XY-200"    # synthetic API App ID
FYERS_LOGIN_ID = "FYSYNTH-LOGIN-1"  # synthetic customer Login ID


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    session._linking_engine = engine
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    engine = db_session._linking_engine
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    auth_mod.SessionLocal = factory
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        auth_mod.SessionLocal = _real_session_local


def make_platform_user(db, email: str | None = None) -> User:
    user = User(
        id=str(uuid4()),
        email=email,
        display_name="Platform User",
        status="active",
        identity_source="email",
        password_hash="seed-not-a-real-hash",
    )
    db.add(user)
    db.commit()
    return user


def login_session(db, user: User, *, with_fyers_token: bool) -> str:
    # set_token(token) → returns a NEW session id bound to that token;
    # None token = platform-only session (user.access_token is None).
    session_id = token_store.set_token(
        "fyers-access-token-value" if with_fyers_token else None,
        persist_to_db=False,
    )
    create_session_record(db, user.id, session_id)
    db.commit()
    return session_id


def store_byob(db, user: User) -> None:
    store_credentials(db, user.id, "FYERS", FYERS_APP_ID, "synthetic-secret-value")
    db.commit()


def fyers_profile() -> dict:
    data = {
        "fy_id": FYERS_LOGIN_ID,
        "name": "Synthetic User",
        "display_name": "Synthetic U",
        "email_id": "synthetic.user@example.com",
        "app_permit": "",
        "appattribution": "",
    }
    return {"s": "ok", "code": 200, "message": "", "data": data}


def mock_fyers_adapter(monkeypatch, *, profile=None, fail_profile=False):
    adapter = AsyncMock()
    adapter.get_connection_context = MagicMock(return_value=None)
    if fail_profile:
        adapter.get_profile = AsyncMock(
            side_effect=BrokerError(BrokerErrorCode.AUTH_REQUIRED, "expired")
        )
    else:
        adapter.get_profile = AsyncMock(return_value=profile or fyers_profile())
    adapter.get_funds = AsyncMock(return_value={"total_balance": 1.0})
    adapter.get_positions = AsyncMock(return_value=[{"symbol": "NSE:SBIN-EQ"}])
    adapter.get_holdings = AsyncMock(return_value=[])
    adapter.get_tradebook = AsyncMock(return_value=[])
    caps = MagicMock()
    caps.state = MagicMock(return_value=MagicMock(value="SUPPORTED"))
    adapter.get_capabilities = MagicMock(return_value=caps)

    instrument = MagicMock()
    instrument.symbol = "NIFTY"
    adapter.resolve_instrument = MagicMock(return_value=instrument)
    obs = MagicMock()
    obs.quote.ltp = 22500.5
    obs.instrument.symbol = "NIFTY"
    obs.source = "FYERS"
    adapter.get_quote = AsyncMock(return_value=obs)
    adapter.get_option_contracts = AsyncMock(return_value=[{"strike": 22500}])
    adapter.extract_account_id = MagicMock(return_value=FYERS_LOGIN_ID)

    gw = MagicMock()
    gw.create.return_value = adapter
    monkeypatch.setattr("app.routers.broker_diagnostics.gateway", gw)
    return adapter


def get_diagnostics(client, session_id: str):
    return client.get("/fyers/diagnostics", headers={"X-Session-Id": session_id})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_404_without_fyers_connection(client, db_session):
    user = make_platform_user(db_session, email="noconn@example.com")
    sid = login_session(db_session, user, with_fyers_token=False)
    resp = get_diagnostics(client, sid)
    assert resp.status_code == 404
    assert "No FYERS connection" in resp.json()["detail"]


def test_user_cannot_reach_another_users_diagnostics(client, db_session, monkeypatch):
    owner = make_platform_user(db_session, email="owner@example.com")
    store_byob(db_session, owner)
    make_platform_user(db_session, email="intruder@example.com")
    intruder_sid = login_session(db_session, owner, with_fyers_token=False)
    # intruder session belongs to... ensure a real second user exists and
    # that their session resolves to a user with NO FYERS connection.
    intruder = db_session.query(User).filter(User.email == "intruder@example.com").one()
    intruder_sid = login_session(db_session, intruder, with_fyers_token=False)
    mock_fyers_adapter(monkeypatch)
    resp = get_diagnostics(client, intruder_sid)
    assert resp.status_code == 404


def test_identity_masked_and_field_named(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="masked@example.com")
    store_byob(db_session, user)
    sid = login_session(db_session, user, with_fyers_token=True)
    mock_fyers_adapter(monkeypatch)
    resp = get_diagnostics(client, sid)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    identity = body["identity"]
    assert identity["ok"] is True
    assert identity["identity_field"] == "fy_id"
    expected_mask = FYERS_LOGIN_ID[:2] + "*" * (len(FYERS_LOGIN_ID) - 4) + FYERS_LOGIN_ID[-2:]
    assert identity["identity_masked"] == expected_mask
    text = resp.text
    assert FYERS_LOGIN_ID not in text, "raw identity must never appear"
    assert "synthetic-secret-value" not in text, "secret must never appear"
    assert "fyers-access-token-value" not in text, "token must never appear"
    assert FYERS_APP_ID not in text, "app id must never appear"


def test_reads_reported_without_raw_payloads(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="reads@example.com")
    store_byob(db_session, user)
    sid = login_session(db_session, user, with_fyers_token=True)
    mock_fyers_adapter(monkeypatch)
    resp = get_diagnostics(client, sid)
    assert resp.status_code == 200
    reads = resp.json()["reads"]
    assert reads["funds"]["ok"] is True
    assert reads["positions"] == {"ok": True, "rows": 1}
    assert reads["holdings"] == {"ok": True, "rows": 0}
    assert reads["tradebook"] == {"ok": True, "rows": 0}
    assert reads["quote"]["ok"] is True and reads["quote"]["ltp_present"] is True
    assert reads["option_contracts"]["ok"] is True


def test_profile_failure_maps_canonical_error(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="failprof@example.com")
    store_byob(db_session, user)
    sid = login_session(db_session, user, with_fyers_token=True)
    mock_fyers_adapter(monkeypatch, fail_profile=True)
    resp = get_diagnostics(client, sid)
    assert resp.status_code == 200  # diagnostics never 500s on broker errors
    body = resp.json()
    assert body["identity"]["ok"] is False
    assert body["identity"]["error"] == BrokerErrorCode.AUTH_REQUIRED.value


def test_read_probes_report_canonical_errors(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="failreads@example.com")
    store_byob(db_session, user)
    sid = login_session(db_session, user, with_fyers_token=True)
    adapter = mock_fyers_adapter(monkeypatch)
    adapter.get_funds = AsyncMock(
        side_effect=BrokerError(BrokerErrorCode.RATE_LIMITED, "slow down")
    )
    resp = get_diagnostics(client, sid)
    assert resp.status_code == 200
    assert resp.json()["reads"]["funds"] == {
        "ok": False,
        "error": BrokerErrorCode.RATE_LIMITED.value,
    }


def test_pending_connection_flagged(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="pending@example.com")
    store_byob(db_session, user)
    sid = login_session(db_session, user, with_fyers_token=True)
    mock_fyers_adapter(monkeypatch)
    conn = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == "FYERS")
        .one()
    )
    conn.broker_account_id = "pending"
    db_session.commit()
    resp = get_diagnostics(client, sid)
    assert resp.status_code == 200
    assert "pending" in (resp.json()["error"] or "")
