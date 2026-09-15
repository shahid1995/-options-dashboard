"""BrokerAuthorization architecture — TDD tests (RED first).

Architecture under test (broker-authorization refactor):

    StrikeNova User
      └── BrokerConnection            (durable ownership ledger)
            └── BrokerAuthorization   (current API authorization — encrypted
                                       token material, its OWN lifecycle)

Core invariants:
  1. Authorization belongs to the BrokerConnection, NOT to any UserSession.
  2. A NEW StrikeNova session for the same user resolves the SAME connection
     and active authorization (no old-session requirement).
  3. Expiring/revoking the initiating session never disconnects the broker.
  4. OAuth callback binds everything to the INITIATING user (signed state).
  5. Tokens are never exposed via repr(), API/diagnostic surfaces.
  6. Cross-user access to (connection, authorization) is impossible.
  7. Refresh is provider-capability gated (Upstox: none; FYERS: refresh token
     exists but automated renewal is PIN-gated → reauthorization required).
  8. FYERS -100 data-only never gains trading capability via authorization.
  9. FYERS callback keeps selecting the real auth_code over the status code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.routers.auth as auth_mod
from app.db import Base, SessionLocal as _real_session_local, get_db
from app.identity import (
    BrokerAuthorization,
    BrokerConnection,
    User,
    UserSession,
    create_session_record,
)
from app.services import token_store
from app.services.broker_authorization import (
    authorization_status,
    persist_connection_authorization,
    resolve_broker_authorization,
    revoke_connection_authorizations,
)
from app.main import app

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
FYERS_APP_ID = "FYERS-TEST-APP-200"
FYERS_LOGIN_ID = "FYERSLOGIN-TEST-001"


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
def client(db_session, monkeypatch):
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


def make_user(db, email: str | None = None) -> User:
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


def new_session_for(db, user: User) -> str:
    """Create an ADDITIONAL (fresh) platform session for an existing user."""
    session_id = token_store.set_token(f"session-{uuid4()}", persist_to_db=False)
    create_session_record(db, user.id, session_id)
    db.commit()
    return session_id


def expire_session(db, session_id: str) -> None:
    from app.identity import hash_session_id

    row = (
        db.query(UserSession)
        .filter(UserSession.session_hash == hash_session_id(session_id))
        .one_or_none()
    )
    assert row is not None
    row.expires_at = NOW - timedelta(hours=1)
    db.commit()


def connect_fyers(db, user: User, account_id: str = FYERS_LOGIN_ID) -> BrokerConnection:
    conn = BrokerConnection(
        id=str(uuid4()),
        user_id=user.id,
        broker="FYERS",
        broker_account_id=account_id,
        status="connected",
        is_default=True,
        app_type="-100",
    )
    db.add(conn)
    db.commit()
    return conn


def fyers_profile() -> dict:
    return {
        "s": "ok",
        "data": {
            "fy_id": FYERS_LOGIN_ID,
            "name": "Test User",
            "email_id": "test@example.com",
            "appattribution": "200",
        },
    }


def mock_fyers_exchange(monkeypatch, access_token: str, refresh_token: str | None = None):
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(return_value=access_token)
    adapter.get_profile = AsyncMock(return_value=fyers_profile())
    adapter.extract_account_id = MagicMock(return_value=FYERS_LOGIN_ID)
    adapter._refresh_token = refresh_token
    monkeypatch.setattr("app.routers.auth.gateway.create", lambda *a, **kw: adapter)
    return adapter


def signed_state_for(db, session_id: str, broker: str = "FYERS") -> str:
    from app.services.token_store import create_oauth_state

    # popup=True mirrors the real popup flow and keeps the completion
    # response inside the app (in-app completion HTML, HTTP 200) exactly
    # like the existing popup-OAuth tests exercise it.
    return create_oauth_state(session_id=session_id, broker=broker, popup=True)


# ---------------------------------------------------------------------------
# 1 — Ownership: authorization belongs to connection, not session
# ---------------------------------------------------------------------------


def test_broker_authorization_belongs_to_connection_not_session(db_session):
    """BrokerAuthorization carries connection_id and has NO session column."""
    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)
    authz = persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="tok-value",
        expires_at=NOW + timedelta(days=1),
        method="oauth_callback",
        now=NOW,
    )
    db.commit()

    assert authz.connection_id == conn.id
    column_names = {c.name for c in BrokerAuthorization.__table__.columns}
    assert "session_hash" not in column_names
    assert "session_id" not in column_names


# ---------------------------------------------------------------------------
# 2 — Fresh session resolves the same authorization (acceptance, part 1)
# ---------------------------------------------------------------------------


def test_new_strikenova_session_can_use_existing_broker_authorization(db_session):
    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)
    persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="connection-token",
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    db.commit()

    # A brand-new platform session for the SAME user resolves the SAME
    # connection + active authorization — no session binding anywhere.
    new_sid = new_session_for(db, user)
    from app.identity import get_active_session

    assert get_active_session(db, new_sid) is not None
    conn2, authz2 = resolve_broker_authorization(db, user.id, "FYERS")
    assert conn2 is not None and authz2 is not None
    assert conn2.id == conn.id
    assert authz2.access_token_plain() == "connection-token"


# ---------------------------------------------------------------------------
# 3 — Expiring/revoking session A never disconnects the broker
# ---------------------------------------------------------------------------


def test_old_session_expiration_does_not_disconnect_broker_connection(db_session):
    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)
    persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="connection-token",
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    db.commit()
    old_sid = new_session_for(db, user)

    # Expire AND revoke the initiating session.
    row = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id)
        .order_by(UserSession.created_at.desc())
        .first()
    )
    row.expires_at = NOW - timedelta(hours=1)
    row.revoked_at = NOW
    db.commit()

    conn2 = (
        db.query(BrokerConnection).filter(BrokerConnection.id == conn.id).one()
    )
    assert conn2.status == "connected"  # NOT disconnected by session expiry
    assert conn2.disconnected_at is None

    conn3, authz3 = resolve_broker_authorization(db, user.id, "FYERS")
    assert conn3.id == conn.id
    assert authz3.access_token_plain() == "connection-token"


# ---------------------------------------------------------------------------
# 4 — OAuth callback binds connection + authorization to the initiating user
# ---------------------------------------------------------------------------


def test_oauth_callback_binds_connection_to_initiating_user(client, db_session, monkeypatch):
    from app.identity import store_credentials

    db = db_session
    user = make_user(db)
    store_credentials(db, user.id, "FYERS", "app-key", "app-secret")
    db.commit()
    sid = new_session_for(db, user)
    mock_fyers_exchange(monkeypatch, "live-access-token", "live-refresh-token")

    state = signed_state_for(db, sid)
    resp = client.get(
        "/auth/callback",
        params={"s": "ok", "code": "200", "auth_code": "real-jwt-code", "state": state},
    )
    assert resp.status_code == 200

    db.expire_all()
    conn = (
        db.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == "FYERS")
        .one()
    )
    assert conn.status == "connected"
    authz = (
        db.query(BrokerAuthorization)
        .filter(BrokerAuthorization.connection_id == conn.id)
        .one()
    )
    assert authz.access_token_plain() == "live-access-token"
    # The initiating SESSION is not the owner of the authorization — the USER is.
    assert authz.connection.user_id == user.id


# ---------------------------------------------------------------------------
# 5 — FYERS keeps selecting the real auth_code over the status code
# ---------------------------------------------------------------------------


def test_fyers_auth_code_preferred_over_status_code(client, db_session, monkeypatch):
    from app.identity import store_credentials

    db = db_session
    user = make_user(db)
    store_credentials(db, user.id, "FYERS", "app-key", "app-secret")
    db.commit()
    sid = new_session_for(db, user)
    adapter = mock_fyers_exchange(monkeypatch, "live-access-token")

    state = signed_state_for(db, sid)
    resp = client.get(
        "/auth/callback",
        params={"s": "ok", "code": "200", "auth_code": "real-jwt-code", "state": state},
    )
    assert resp.status_code == 200
    exchanged = adapter.exchange_authorization_code.call_args[0][0]
    assert exchanged == "real-jwt-code"
    assert exchanged != "200"


# ---------------------------------------------------------------------------
# 6 — Authorization persisted after OAuth (with refresh when returned)
# ---------------------------------------------------------------------------


def test_fyers_authorization_persisted_after_oauth(client, db_session, monkeypatch):
    from app.identity import store_credentials

    db = db_session
    user = make_user(db)
    store_credentials(db, user.id, "FYERS", "app-key", "app-secret")
    db.commit()
    sid = new_session_for(db, user)
    mock_fyers_exchange(monkeypatch, "live-access-token", "live-refresh-token")

    state = signed_state_for(db, sid)
    resp = client.get(
        "/auth/callback",
        params={"s": "ok", "code": "200", "auth_code": "real-jwt-code", "state": state},
    )
    assert resp.status_code == 200

    db.expire_all()
    conn = (
        db.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == "FYERS")
        .one()
    )
    authz = (
        db.query(BrokerAuthorization)
        .filter(BrokerAuthorization.connection_id == conn.id)
        .one()
    )
    assert authz.access_token_plain() == "live-access-token"
    assert authz.refresh_token_plain() == "live-refresh-token"
    assert authz.refresh_token_encrypted is not None
    assert authz.status == "active"
    assert authz.method == "oauth_callback"
    assert conn.status == "connected"


# ---------------------------------------------------------------------------
# 7 — Tokens never exposed: repr and API/diagnostic surfaces
# ---------------------------------------------------------------------------


def test_tokens_never_exposed_in_api_or_diagnostics(db_session):
    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)
    authz = persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="super-secret-access-token",
        refresh_token="super-secret-refresh-token",
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    db.commit()

    # repr() and str() must be masked.
    for rendered in (repr(authz), str(authz)):
        assert "super-secret-access-token" not in rendered
        assert "super-secret-refresh-token" not in rendered
    # The column itself must not be repr'd by SQLAlchemy defaults either.
    assert "super-secret-access-token" not in repr(authz.connection)

    # Public status view exposes metadata only.
    view = authz.public_status()
    assert view["status"] == "active"
    assert view["connection_id"] == conn.id
    flat = str(view)
    assert "super-secret-access-token" not in flat
    assert "super-secret-refresh-token" not in flat


# ---------------------------------------------------------------------------
# 8 — Different user can never resolve another user's authorization
# ---------------------------------------------------------------------------


def test_different_user_cannot_use_existing_broker_authorization(db_session):
    db = db_session
    user_a = make_user(db, email="a@example.com")
    user_b = make_user(db, email="b@example.com")
    conn = connect_fyers(db, user_a)
    persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="user-a-token",
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    db.commit()

    # User B has a fresh valid session but owns NO FYERS connection.
    new_session_for(db, user_b)
    result = resolve_broker_authorization(db, user_b.id, "FYERS")
    assert result == (None, None)

    # Even a direct row lookup by connection id yields nothing usable for B:
    # authorization access is only through the user→connection→authorization
    # path, and B's user_id never matches the connection's owner.
    authz_rows = (
        db.query(BrokerAuthorization)
        .join(BrokerConnection, BrokerAuthorization.connection_id == BrokerConnection.id)
        .filter(BrokerConnection.user_id == user_b.id)
        .all()
    )
    assert authz_rows == []


# ---------------------------------------------------------------------------
# 9 — Refresh is provider-capability gated
# ---------------------------------------------------------------------------


def test_refresh_is_provider_capability_gated(db_session):
    from app.services.renewal_strategy import (
        BrokerNotRefreshableError,
        get_renewal_strategy,
    )

    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)
    authz = persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="tok",
        refresh_token="fyers-refresh",
        expires_at=NOW + timedelta(hours=1),
        refresh_expires_at=NOW + timedelta(days=15),
        now=NOW,
    )
    db.commit()

    # Upstox: no refresh capability at all.
    upstox = get_renewal_strategy("UPSTOX")
    assert upstox.can_refresh() is False
    with pytest.raises(BrokerNotRefreshableError):
        upstox.refresh_authorization(db, authz)

    # FYERS: refresh token exists but automated renewal is PIN-gated —
    # the strategy must NOT attempt it; reauthorization is required.
    fyers = get_renewal_strategy("FYERS")
    assert fyers.can_refresh() is False  # automated refresh not permitted
    assert fyers.requires_reauthorization(authz, now=NOW + timedelta(hours=2)) is True
    with pytest.raises(BrokerNotRefreshableError):
        fyers.refresh_authorization(db, authz)

    # Expired authorization reports its status honestly.
    assert authorization_status(authz, now=NOW + timedelta(hours=2)) == "expired"
    assert authorization_status(authz, now=NOW) == "active"


# ---------------------------------------------------------------------------
# 10 — FYERS -100 data-only never gains trading capability
# ---------------------------------------------------------------------------


def test_fyers_data_only_does_not_gain_trading_capability(db_session):
    from app.services.renewal_strategy import get_renewal_strategy

    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)  # app_type="-100"
    persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="tok",
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    db.commit()

    strategy = get_renewal_strategy("FYERS")
    caps = strategy.capabilities(app_type=conn.app_type)
    assert caps["trading"] is False
    assert caps["data"] is True

    db.expire_all()
    conn2 = db.query(BrokerConnection).filter(BrokerConnection.id == conn.id).one()
    assert conn2.trading_status != "active"


# ---------------------------------------------------------------------------
# Acceptance scenario I — full Session A → expire → Session B flow
# ---------------------------------------------------------------------------


def test_acceptance_session_independence_end_to_end(client, db_session, monkeypatch):
    """SESSION A connects FYERS → expires → SESSION B (same user) resolves
    connection + active authorization; different user resolves nothing."""
    from app.identity import store_credentials

    db = db_session
    user_a = make_user(db, email="owner@example.com")
    user_b = make_user(db, email="intruder@example.com")

    store_credentials(db, user_a.id, "FYERS", "app-key", "app-secret")
    db.commit()
    session_a = new_session_for(db, user_a)

    mock_fyers_exchange(monkeypatch, "live-access-token", "live-refresh-token")
    resp = client.get(
        "/auth/callback",
        params={
            "s": "ok",
            "code": "200",
            "auth_code": "real-jwt-code",
            "state": signed_state_for(db, session_a),
        },
    )
    assert resp.status_code == 200

    db.expire_all()
    conn = (
        db.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user_a.id, BrokerConnection.broker == "FYERS")
        .one()
    )
    authz = (
        db.query(BrokerAuthorization)
        .filter(BrokerAuthorization.connection_id == conn.id)
        .one()
    )
    assert authz.status == "active"

    # --- Invalidate SESSION A completely (expire + revoke).
    session_a_rows = (
        db.query(UserSession).filter(UserSession.user_id == user_a.id).all()
    )
    for row in session_a_rows:
        row.expires_at = NOW - timedelta(hours=1)
        row.revoked_at = NOW
    db.commit()

    # --- SESSION B (same user) resolves the SAME connection + authorization.
    session_b = new_session_for(db, user_a)
    from app.identity import get_active_session

    assert get_active_session(db, session_b) is not None
    conn_b, authz_b = resolve_broker_authorization(db, user_a.id, "FYERS")
    assert conn_b is not None and authz_b is not None
    assert conn_b.id == conn.id
    assert authz_b.id == authz.id
    assert authz_b.access_token_plain() == "live-access-token"

    # --- A DIFFERENT user (session C) resolves nothing.
    session_c = new_session_for(db, user_b)
    assert get_active_session(db, session_c) is not None
    assert resolve_broker_authorization(db, user_b.id, "FYERS") == (None, None)


# ---------------------------------------------------------------------------
# Revocation lifecycle helper coverage
# ---------------------------------------------------------------------------


def test_revoke_connection_authorizations(db_session):
    db = db_session
    user = make_user(db)
    conn = connect_fyers(db, user)
    authz = persist_connection_authorization(
        db,
        connection_id=conn.id,
        broker="FYERS",
        access_token="tok",
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    db.commit()

    revoke_connection_authorizations(db, conn.id, reason="test_revoke", now=NOW)
    db.commit()
    db.expire_all()
    row = db.query(BrokerAuthorization).filter(BrokerAuthorization.id == authz.id).one()
    assert row.status == "revoked"
    # Connection survives revocation (durable ownership); the authorization
    # no longer resolves as active.
    conn_after, authz_after = resolve_broker_authorization(db, user.id, "FYERS")
    assert conn_after.id == conn.id
    assert authz_after is None
