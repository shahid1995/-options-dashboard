"""FYERS identity integration (Phase 17) — the multi-broker identity flow
run with a synthetic FYERS provider response.

Target architecture:

    StrikeNova User
     ├── UPSTOX / UCC-A
     └── FYERS  / FYERS-LOGIN-ID        (customer Login ID — NEVER the App ID)

Invariants under test:

* one User, two BrokerConnections (UPSTOX + FYERS);
* a second StrikeNova user cannot claim the same FYERS identity
  (ownership ledger arbitration — rejected, never transferred);
* the FYERS API App ID is NEVER used as ownership identity;
* the FYERS refresh token is persisted encrypted (never discarded,
  never stored in plaintext).

All broker identities are synthetic — no real broker data appears anywhere.
Broker seams (exchange / profile / extract_account_id) are mocked per the
repository's established technique (test_auth_router.py,
test_identity_linking.py).
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
from app.identity import BrokerConnection, BrokerToken, User, create_session_record
from app.services import token_store
from app.main import app

FYERS_APP_ID = "SPSYNTH01XY-200"   # synthetic API App ID
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def login_initiator(db, user: User) -> str:
    session_id = token_store.set_token(f"initiator-session-{uuid4()}", persist_to_db=False)
    create_session_record(db, user.id, session_id)
    db.commit()
    return session_id


def store_byob(db, user: User, broker: str) -> None:
    store_credentials(db, user.id, broker, f"{broker.lower()}-key", f"{broker.lower()}-secret")
    db.commit()


from app.identity import store_credentials  # noqa: E402


def fyers_profile() -> dict:
    """Synthetic FYERS profile payload (expected v3 shape).

    The Login-ID field is the to-be-confirmed candidate; the App ID and
    email are present to prove they are never selected as identity.
    """
    return {
        "s": "ok",
        "data": {
            "fy_id": FYERS_LOGIN_ID,
            "name": "Synthetic Human",
            "email_id": "synthetic@example.com",
            "appattribution": "200",
        },
    }


def upstox_profile(account_id: str) -> dict:
    return {
        "status": "success",
        "data": {
            "broker": "UPSTOX",
            "user_id": account_id,
            "email": f"{account_id.lower()}@broker.example",
            "user_name": "Broker Human",
            "is_active": True,
        },
    }


def mock_fyers_adapter(monkeypatch, profile: dict, refresh_token: str | None = None):
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(return_value="fyers-access-token-value")
    adapter.get_profile = AsyncMock(return_value=profile)
    adapter.extract_account_id = MagicMock(return_value=profile["data"]["fy_id"])
    if refresh_token is not None:
        adapter._refresh_token = refresh_token
    gw = MagicMock()
    gw.create.return_value = adapter
    monkeypatch.setattr("app.routers.auth.gateway", gw)
    return adapter


def connect_fyers(client, db, user: User, monkeypatch, *, refresh_token: str | None = None):
    store_byob(db, user, "FYERS")
    sid = login_initiator(db, user)
    mock_fyers_adapter(monkeypatch, fyers_profile(), refresh_token=refresh_token)
    state = token_store.create_oauth_state(session_id=sid, broker="FYERS")
    return client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )


def connect_upstox(client, db, user: User, account_id: str, monkeypatch):
    store_byob(db, user, "UPSTOX")
    sid = login_initiator(db, user)
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(return_value="upstox-access-token-value")
    adapter.get_profile = AsyncMock(return_value=upstox_profile(account_id))
    adapter.extract_account_id = MagicMock(return_value=account_id)
    gw = MagicMock()
    gw.create.return_value = adapter
    monkeypatch.setattr("app.routers.auth.gateway", gw)
    state = token_store.create_oauth_state(session_id=sid, broker="UPSTOX")
    return client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )


def login_error_of(resp) -> str:
    from urllib.parse import urlsplit, parse_qs

    q = parse_qs(urlsplit(resp.headers["location"]).query)
    return q.get("login_error", [""])[0]


def live_connections(db, user: User):
    return (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user.id,
            BrokerConnection.broker_account_id.notin_(["pending", "data-only"]),
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Test 1 — one User, two BrokerConnections (UPSTOX + FYERS)
# ---------------------------------------------------------------------------


def test_one_user_two_broker_connections(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="multi@example.com")

    r1 = connect_upstox(client, db_session, user, "UCC-MULTI-1", monkeypatch)
    assert r1.status_code == 307 and login_error_of(r1) == ""

    r2 = connect_fyers(client, db_session, user, monkeypatch)
    assert r2.status_code == 307, f"FYERS connect failed: {login_error_of(r2)}"
    assert login_error_of(r2) == ""

    assert db_session.query(User).count() == 1, "second broker must never fork a User"
    conns = {(c.broker, c.broker_account_id) for c in live_connections(db_session, user)}
    assert conns == {("UPSTOX", "UCC-MULTI-1"), ("FYERS", FYERS_LOGIN_ID)}
    assert {c.user_id for c in live_connections(db_session, user)} == {user.id}


# ---------------------------------------------------------------------------
# Test 2 — second user cannot claim the same FYERS identity
# ---------------------------------------------------------------------------


def test_second_user_cannot_claim_fyers_identity(client, db_session, monkeypatch):
    owner = make_platform_user(db_session, email="owner@example.com")
    r1 = connect_fyers(client, db_session, owner, monkeypatch)
    assert r1.status_code == 307 and login_error_of(r1) == ""

    attacker = make_platform_user(db_session, email="attacker@example.com")
    store_byob(db_session, attacker, "FYERS")
    sid = login_initiator(db_session, attacker)
    mock_fyers_adapter(monkeypatch, fyers_profile())
    state = token_store.create_oauth_state(session_id=sid, broker="FYERS")
    before = db_session.query(BrokerConnection).count()

    r2 = client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )

    assert r2.status_code == 307
    assert login_error_of(r2) == "broker_identity_in_use"
    assert db_session.query(BrokerConnection).count() == before, "rejected attempt writes nothing"
    conn = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.broker == "FYERS")
        .filter(BrokerConnection.broker_account_id == FYERS_LOGIN_ID)
        .one()
    )
    assert conn.user_id == owner.id, "ownership is never transferred"


# ---------------------------------------------------------------------------
# Test 3 — the API App ID is NEVER the ownership identity
# ---------------------------------------------------------------------------


def test_app_id_is_never_the_identity(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="appid@example.com")
    r = connect_fyers(client, db_session, user, monkeypatch)
    assert r.status_code == 307 and login_error_of(r) == ""

    conns = [c for c in live_connections(db_session, user) if c.broker == "FYERS"]
    assert len(conns) == 1
    assert conns[0].broker_account_id == FYERS_LOGIN_ID
    assert conns[0].broker_account_id != FYERS_APP_ID, (
        "the API App ID must never become broker_account_id"
    )


# ---------------------------------------------------------------------------
# Test 4 — legacy stamp does not block FYERS; stamp is never overwritten
# ---------------------------------------------------------------------------


def test_legacy_stamp_does_not_block_fyers(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="stamped@example.com")
    user.broker_provider = "UPSTOX"
    user.broker_user_id = "UP-LEGACY"
    db_session.commit()

    r = connect_fyers(client, db_session, user, monkeypatch)
    assert r.status_code == 307 and login_error_of(r) == ""
    assert db_session.query(User).count() == 1
    assert [c.broker for c in live_connections(db_session, user)] == ["FYERS"]
    db_session.refresh(user)
    assert user.broker_provider == "UPSTOX"
    assert user.broker_user_id == "UP-LEGACY"


# ---------------------------------------------------------------------------
# Test 5 — FYERS refresh token persisted encrypted, never discarded
# ---------------------------------------------------------------------------


def test_fyers_refresh_token_persisted_encrypted(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="refresh@example.com")
    r = connect_fyers(
        client, db_session, user, monkeypatch, refresh_token="fyers-refresh-secret-value"
    )
    assert r.status_code == 307 and login_error_of(r) == ""

    token_row = db_session.query(BrokerToken).filter(
        BrokerToken.broker_refresh_token_encrypted.isnot(None)
    ).one()
    stored = token_row.broker_refresh_token_encrypted
    assert stored != "fyers-refresh-secret-value", "refresh token must be encrypted at rest"
    from app.crypto import decrypt

    assert decrypt(stored) == "fyers-refresh-secret-value"
    assert token_row.broker_refresh_token_expires_at is not None


def test_fyers_refresh_token_absent_ok(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="norefresh@example.com")
    r = connect_fyers(client, db_session, user, monkeypatch, refresh_token=None)
    assert r.status_code == 307 and login_error_of(r) == ""
    assert (
        db_session.query(BrokerToken)
        .filter(BrokerToken.broker_refresh_token_encrypted.isnot(None))
        .count()
    ) == 0


# ---------------------------------------------------------------------------
# Staging validation regression — FYERS redirects back with `auth_code`,
# its own parameter name, instead of OAuth's standard `code`.
# ---------------------------------------------------------------------------


def test_fyers_callback_accepts_auth_code_param(client, db_session, monkeypatch):
    """The FYERS v3 consent redirect appends `auth_code` (not `code`) to the
    callback URL. The callback must accept either name — the broker identity
    comes from the signed state, so the alias cannot cross broker flows."""
    user = make_platform_user(db_session, email="authcode@example.com")
    store_byob(db_session, user, "FYERS")
    sid = login_initiator(db_session, user)
    mock_fyers_adapter(monkeypatch, fyers_profile())
    state = token_store.create_oauth_state(session_id=sid, broker="FYERS")
    resp = client.get(
        "/auth/callback",
        params={"auth_code": "fyers-auth-code-value", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 307, f"auth_code alias failed: {login_error_of(resp)}"
    assert login_error_of(resp) == ""
    fyers_conns = [
        c for c in live_connections(db_session, user) if c.broker == "FYERS"
    ]
    assert len(fyers_conns) == 1
    assert fyers_conns[0].broker_account_id == FYERS_LOGIN_ID
