"""Session-bound Upstox identity linking — authorized implementation tests.

Authoritative design: docs/architecture/UPSTOX_IDENTITY_LINKING_DESIGN.md
(commit e897ce4), §17 reconciliation contract.

Core rule under test:

    Broker OAuth may link a broker identity only to the
    already-authenticated StrikeNova user whose session initiated
    the connection. The callback MUST NEVER create a platform User.
    Email matching MUST NEVER authorize linking. A broker identity
    owned by another user MUST NEVER be transferred.

External Upstox seams (exchange / profile / extract_account_id) are
mocked per the repository's established technique (test_auth_router.py).
No real broker credentials, codes, or tokens appear anywhere.
"""

from __future__ import annotations

import threading
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
from app.identity import (
    BrokerConnection,
    BrokerToken,
    User,
    UserSession,
    create_session_record,
    hash_session_id,
    store_credentials,
)
from app.services import token_store


# ---------------------------------------------------------------------------
# Fixtures — per-call fresh sessions on one shared in-memory engine,
# mirroring production (the callback opens its own sessions and relies on
# COMMITTED data; test helpers therefore commit their seeds).
# ---------------------------------------------------------------------------
@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    session._linking_engine = engine  # shared with the client fixture
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


from app.main import app  # noqa: E402  (import after fixtures defined)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_platform_user(db, email: str | None = None, *, stamped=None) -> User:
    """A StrikeNova platform user (email/password origin by default)."""
    user = User(
        id=str(uuid4()),
        email=email,
        display_name="Platform User",
        status="active",
        identity_source="email",
        password_hash="seed-not-a-real-hash",
    )
    if stamped is not None:
        provider, broker_user_id = stamped
        user.broker_provider = provider
        user.broker_user_id = broker_user_id
    db.add(user)
    db.commit()
    return user


def login_initiator(db, user: User) -> str:
    """Authenticated platform session for the initiating user."""
    session_id = token_store.set_token(
        f"initiator-session-{uuid4()}", persist_to_db=False
    )
    create_session_record(db, user.id, session_id)
    db.commit()
    return session_id


def store_byob(db, user: User) -> None:
    store_credentials(db, user.id, "UPSTOX", "byob-key", "byob-secret")
    db.commit()


def broker_profile(user_id: str, email: str, name: str = "Broker Human") -> dict:
    return {
        "status": "success",
        "data": {
            "broker": "UPSTOX",
            "user_id": user_id,
            "email": email,
            "user_name": name,
            "is_active": True,
        },
    }


def mock_upstox(monkeypatch, profile: dict):
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(return_value="upstox-access-token-value")
    adapter.get_profile = AsyncMock(return_value=profile)
    # extract_account_id is a @staticmethod — must return str, not coroutine
    adapter.extract_account_id = MagicMock(return_value=profile["data"]["user_id"])
    gw = MagicMock()
    gw.create.return_value = adapter
    monkeypatch.setattr("app.routers.auth.gateway", gw)
    return adapter


def counts(db):
    return {
        "users": db.query(User).count(),
        "connections": db.query(BrokerConnection).count(),
        "tokens": db.query(BrokerToken).count(),
        "sessions": db.query(UserSession).count(),
    }


def connect_flow(
    client, db, user: User, profile: dict, monkeypatch, *, store: bool = True
):
    """Full connect flow. ``store=False`` reproduces a reconnect where the
    BYOB credentials already exist (no second /auth/connect call)."""
    if store:
        store_byob(db, user)
    sid = login_initiator(db, user)
    mock_upstox(monkeypatch, profile)
    state = token_store.create_oauth_state(session_id=sid, broker="UPSTOX")
    return client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )


def start_connect(db, user: User, profile: dict, monkeypatch) -> str:
    """Prepare (BYOB + session + state) without firing the callback, so
    tests can snapshot counts between setup and the callback under test."""
    store_byob(db, user)
    sid = login_initiator(db, user)
    mock_upstox(monkeypatch, profile)
    return token_store.create_oauth_state(session_id=sid, broker="UPSTOX")


def login_error_of(resp) -> str:
    from urllib.parse import urlsplit, parse_qs

    q = parse_qs(urlsplit(resp.headers["location"]).query)
    return q.get("login_error", [""])[0]


# ---------------------------------------------------------------------------
# Phase 1 RED: the original defect — no duplicate user on email collision
# ---------------------------------------------------------------------------
def test_callback_links_identity_to_session_user_when_emails_match(
    client, db_session, monkeypatch
):
    """THE regression: platform user A (email X) connects Upstox identity X
    whose profile email is also X. The old flow tried to INSERT a second
    User -> UniqueViolation -> account_setup_failed. The authorized flow
    must link to A and succeed."""
    user = make_platform_user(db_session, email="trader@example.com")
    profile = broker_profile("UPSTOX-UCC-1", email="trader@example.com")

    state = start_connect(db_session, user, profile, monkeypatch)
    # Snapshot AFTER setup: store_byob() legitimately created the pending
    # BrokerConnection and login_initiator() the platform session. The
    # callback UPGRADES the pending row in place (design §4.3/§17.3) —
    # it must not duplicate it.
    before = counts(db_session)
    resp = client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 307, f"callback failed: {login_error_of(resp)}"
    assert login_error_of(resp) == ""
    after = counts(db_session)
    assert after["users"] == before["users"], "callback must NEVER create a User"
    # pending row upgraded in place — total connection count unchanged, but
    # the live (non-pending) ownership row appears exactly once.
    assert after["connections"] == before["connections"]
    assert (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.broker_account_id != "pending")
        .count()
    ) == 1
    assert after["tokens"] == before["tokens"] + 1
    assert after["sessions"] == before["sessions"] + 1

    conn = db_session.query(BrokerConnection).one()
    assert conn.user_id == user.id
    assert conn.broker == "UPSTOX"
    assert conn.broker_account_id == "UPSTOX-UCC-1"
    # legacy stamping NULL -> identity
    db_session.refresh(user)
    assert user.broker_provider == "UPSTOX"
    assert user.broker_user_id == "UPSTOX-UCC-1"
    # profile email must never overwrite users.email
    assert user.email == "trader@example.com"


# ---------------------------------------------------------------------------
# Case A/B: new identity links; same-user reconnect is idempotent
# ---------------------------------------------------------------------------
def test_new_broker_identity_links_to_session_user(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")
    profile = broker_profile("UCC-A", email="broker-a@upstox.example")

    resp = connect_flow(client, db_session, user, profile, monkeypatch)

    assert resp.status_code == 307
    assert login_error_of(resp) == ""
    assert counts(db_session)["users"] == 1
    conn = db_session.query(BrokerConnection).one()
    assert conn.user_id == user.id and conn.broker_account_id == "UCC-A"
    db_session.refresh(user)
    assert user.email == "a@example.com"  # broker email is metadata only


def test_same_user_reconnect_is_idempotent(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")
    profile = broker_profile("UCC-A", email="broker-a@upstox.example")

    first = connect_flow(client, db_session, user, profile, monkeypatch)
    assert first.status_code == 307 and login_error_of(first) == ""
    conn_id_first = db_session.query(BrokerConnection).one().id
    sessions_after_first = counts(db_session)["sessions"]

    # reconnect: credentials already stored — no second /auth/connect.
    # Setup (fresh initiator session) runs first; the delta snapshot is
    # taken AFTER all legitimate setup rows exist.
    sid2 = login_initiator(db_session, user)
    mock_upstox(monkeypatch, profile)
    before_second = counts(db_session)
    state2 = token_store.create_oauth_state(session_id=sid2, broker="UPSTOX")
    second = client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state2},
        follow_redirects=False,
    )
    assert second.status_code == 307 and login_error_of(second) == ""
    assert db_session.query(BrokerConnection).count() == 1
    assert db_session.query(BrokerConnection).one().id == conn_id_first
    # a NEW broker session is minted per callback
    after_second = counts(db_session)
    assert after_second["sessions"] == before_second["sessions"] + 1
    assert after_second["tokens"] == before_second["tokens"] + 1
    assert after_second["connections"] == before_second["connections"]
    assert after_second["users"] == 1


# ---------------------------------------------------------------------------
# Case C: broker identity owned by another user — reject, never transfer
# ---------------------------------------------------------------------------
def test_broker_identity_owned_by_other_user_is_rejected(
    client, db_session, monkeypatch
):
    owner = make_platform_user(db_session, email="owner@example.com")
    owner_conn = BrokerConnection(
        id=str(uuid4()),
        user_id=owner.id,
        broker="UPSTOX",
        broker_account_id="UCC-X",
        status="connected",
    )
    db_session.add(owner_conn)
    db_session.commit()

    attacker = make_platform_user(db_session, email="attacker@example.com")
    state = start_connect(
        db_session, attacker, broker_profile("UCC-X", "attacker@upstox.example"), monkeypatch
    )
    before = counts(db_session)

    resp = client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert login_error_of(resp) == "broker_identity_in_use"
    after = counts(db_session)
    assert after == before, "rejected attempt must write nothing"
    db_session.refresh(owner_conn)
    assert owner_conn.user_id == owner.id  # ownership preserved


def test_conflicting_legacy_stamp_is_rejected_not_overwritten(
    client, db_session, monkeypatch
):
    """Phase 5: user already stamped with a DIFFERENT broker identity —
    reject rather than corrupt the existing identity metadata."""
    user = make_platform_user(db_session, email="a@example.com", stamped=("UPSTOX", "UCC-OLD"))
    state = start_connect(db_session, user, broker_profile("UCC-NEW", "a@upstox.example"), monkeypatch)
    before = counts(db_session)

    resp = client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert login_error_of(resp) == "broker_identity_in_use"
    assert counts(db_session) == before
    db_session.refresh(user)
    assert user.broker_user_id == "UCC-OLD"  # untouched


def test_same_legacy_stamp_is_a_noop(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com", stamped=("UPSTOX", "UCC-A"))
    resp = connect_flow(
        client, db_session, user, broker_profile("UCC-A", "a@upstox.example"), monkeypatch
    )
    assert resp.status_code == 307 and login_error_of(resp) == ""
    db_session.refresh(user)
    assert user.broker_provider == "UPSTOX" and user.broker_user_id == "UCC-A"
    assert counts(db_session)["connections"] == 1


# ---------------------------------------------------------------------------
# Phase 16: email edge cases — email is NEVER authority
# ---------------------------------------------------------------------------
def test_email_mismatch_is_allowed(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")
    resp = connect_flow(
        client, db_session, user, broker_profile("UCC-A", "totally-different@upstox.example"), monkeypatch
    )
    assert resp.status_code == 307 and login_error_of(resp) == ""
    db_session.refresh(user)
    assert user.email == "a@example.com"
    # profile email retained as informational metadata on the connection
    conn = db_session.query(BrokerConnection).one()
    assert "totally-different@upstox.example" in (conn.provider_metadata_json or "")


def test_email_collision_with_another_user_is_not_authority(
    client, db_session, monkeypatch
):
    other = make_platform_user(db_session, email="victim@example.com")
    connector = make_platform_user(db_session, email="a@example.com")
    before_other = db_session.query(User).filter(User.id == other.id).one()

    resp = connect_flow(
        client, db_session, connector, broker_profile("UCC-A", "victim@example.com"), monkeypatch
    )

    assert resp.status_code == 307 and login_error_of(resp) == ""
    conn = db_session.query(BrokerConnection).one()
    assert conn.user_id == connector.id, "email match must NOT redirect ownership"
    db_session.refresh(other)
    assert other.email == before_other.email
    assert other.broker_user_id is None  # other user untouched


# ---------------------------------------------------------------------------
# Phase 17: state validation (expired / forged / replayed)
# ---------------------------------------------------------------------------
def test_forged_state_rejected(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")
    store_byob(db_session, user)
    login_initiator(db_session, user)
    mock_upstox(monkeypatch, broker_profile("UCC-A", "a@upstox.example"))

    resp = client.get(
        "/auth/callback", params={"code": "c", "state": "forged-state"}, follow_redirects=False
    )
    assert resp.status_code == 400
    # no non-pending connection may appear (the BYOB pending row is setup)
    live = db_session.query(BrokerConnection).filter(
        BrokerConnection.broker_account_id != "pending"
    ).count()
    assert live == 0


def test_replayed_state_rejected(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")
    store_byob(db_session, user)
    sid = login_initiator(db_session, user)
    mock_upstox(monkeypatch, broker_profile("UCC-A", "a@upstox.example"))
    state = token_store.create_oauth_state(session_id=sid, broker="UPSTOX")

    first = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert first.status_code == 307 and login_error_of(first) == ""
    connections_after_first = counts(db_session)["connections"]
    tokens_after_first = counts(db_session)["tokens"]
    sessions_after_first = counts(db_session)["sessions"]

    replay = client.get("/auth/callback", params={"code": "c2", "state": state}, follow_redirects=False)
    assert replay.status_code == 400
    assert counts(db_session)["connections"] == connections_after_first
    assert counts(db_session)["tokens"] == tokens_after_first
    assert counts(db_session)["sessions"] == sessions_after_first


def test_expired_state_rejected(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")
    store_byob(db_session, user)
    sid = login_initiator(db_session, user)
    mock_upstox(monkeypatch, broker_profile("UCC-A", "a@upstox.example"))
    state = token_store.create_oauth_state(session_id=sid, broker="UPSTOX")
    # The expiry check reads the SIGNED payload timestamp against
    # _STATE_TTL_SECONDS (the GC-map timestamp is not authoritative), so
    # expiry is simulated by shrinking the TTL to zero — still a genuine
    # TTL-rejection path, no production code change.
    monkeypatch.setattr(token_store, "_STATE_TTL_SECONDS", 0)

    resp = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert resp.status_code == 400
    live = db_session.query(BrokerConnection).filter(
        BrokerConnection.broker_account_id != "pending"
    ).count()
    assert live == 0


# ---------------------------------------------------------------------------
# Phase 13: atomic rollback — forced failure AFTER connection creation
# ---------------------------------------------------------------------------
def test_forced_db_failure_after_connection_rolls_back_everything(
    client, db_session, monkeypatch
):
    user = make_platform_user(db_session, email="a@example.com")
    state = start_connect(db_session, user, broker_profile("UCC-A", "a@upstox.example"), monkeypatch)
    before = counts(db_session)

    # Fail inside the same transaction, after the BrokerConnection flush:
    # poison the token-persistence step.
    def boom(*a, **k):
        raise RuntimeError("simulated DB failure after connection creation")

    monkeypatch.setattr("app.services.token_store.persist_broker_token_row", boom)
    resp = client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert login_error_of(resp) == "account_setup_failed"
    assert counts(db_session) == before, (
        "rollback must remove connection + session + token rows alike"
    )
    # the discarded Upstox token must not appear anywhere in the DB
    assert db_session.query(BrokerToken).count() == before["tokens"]


# ---------------------------------------------------------------------------
# Phase 14/15: concurrency — deterministic recover path (always-run)
# + real-thread variants (Postgres-gated harness pattern)
# ---------------------------------------------------------------------------
def test_same_user_race_recovers_via_reread(client, db_session, monkeypatch):
    """Simulate losing the same-user INSERT race: the connection INSERT hits
    the unique constraint once; the callback must re-read and finish as an
    idempotent reconnect — never surface an IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    user = make_platform_user(db_session, email="a@example.com")
    profile = broker_profile("UCC-A", "a@upstox.example")
    store_byob(db_session, user)
    sid = login_initiator(db_session, user)
    mock_upstox(monkeypatch, profile)

    state = token_store.create_oauth_state(session_id=sid, broker="UPSTOX")

    calls = {"n": 0}
    real_gocc = auth_mod.get_or_create_connection

    def racing_gocc(db, user_id, broker, account_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # emulate the concurrent winner having committed between our
            # SELECT and INSERT: flush a conflicting row from "another
            # session" perspective by raising the IntegrityError the
            # unique constraint would produce.
            raise IntegrityError(
                "INSERT failed", None, Exception("uq_broker_connection duplicate")
            )
        return real_gocc(db, user_id, broker, account_id, **kw)

    monkeypatch.setattr("app.routers.auth.get_or_create_connection", racing_gocc)

    resp = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert resp.status_code == 307, f"race recover failed: {login_error_of(resp)}"
    assert login_error_of(resp) == ""
    assert db_session.query(BrokerConnection).count() == 1
    assert calls["n"] >= 2, "recover path must re-read and retry"


def test_cross_user_race_loser_surfaces_broker_identity_in_use(
    client, db_session, monkeypatch
):
    """Simulate the cross-user race: the pre-check misses (owner committed
    concurrently), the global unique index rejects the INSERT, and the
    callback must classify the conflict as broker_identity_in_use."""
    from sqlalchemy.exc import IntegrityError

    owner = make_platform_user(db_session, email="owner@example.com")
    conn = BrokerConnection(
        id=str(uuid4()),
        user_id=owner.id,
        broker="UPSTOX",
        broker_account_id="UCC-X",
        status="connected",
    )
    db_session.add(conn)
    db_session.commit()

    challenger = make_platform_user(db_session, email="b@example.com")
    store_byob(db_session, challenger)
    sid = login_initiator(db_session, challenger)
    mock_upstox(monkeypatch, broker_profile("UCC-X", "b@upstox.example"))
    state = token_store.create_oauth_state(session_id=sid, broker="UPSTOX")

    calls = {"n": 0}
    real_gocc = auth_mod.get_or_create_connection

    def racing_gocc(db, user_id, broker, account_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError(
                "INSERT failed", None, Exception("uq_broker_identity_global duplicate")
            )
        return real_gocc(db, user_id, broker, account_id, **kw)

    monkeypatch.setattr("app.routers.auth.get_or_create_connection", racing_gocc)

    resp = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert resp.status_code == 307
    assert login_error_of(resp) == "broker_identity_in_use"
    db_session.refresh(conn)
    assert conn.user_id == owner.id


# ---------------------------------------------------------------------------
# Global uniqueness index (SQLite validates the partial-index SQL itself)
# ---------------------------------------------------------------------------
def test_global_partial_index_blocks_cross_user_duplicate_and_allows_pending():
    from sqlalchemy import text

    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, BrokerConnection.__table__, BrokerToken.__table__, UserSession.__table__],
    )
    with engine.begin() as cx:
        cx.execute(
            text(
                "CREATE UNIQUE INDEX uq_broker_identity_global "
                "ON broker_connections (broker, broker_account_id) "
                "WHERE broker_account_id <> 'pending'"
            )
        )
        u1, u2 = "u1-" + str(uuid4()), "u2-" + str(uuid4())
        for uid in (u1, u2):
            cx.execute(
                text(
                    "INSERT INTO users (id, status, identity_source, created_at, updated_at) "
                    "VALUES (:i, 'active', 'email', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"i": uid},
            )
        for cid, uid, acct in (
            ("c1", u1, "UCC-9"),
            ("c2", u2, "UCC-9"),  # cross-user duplicate -> must be rejected
            ("p1", u1, "pending"),
            ("p2", u2, "pending"),  # pending sentinel rows stay legal
        ):
            stmt = text(
                "INSERT INTO broker_connections (id, user_id, broker, broker_account_id, "
                "is_default, status, capability_mode, data_status, trading_status, "
                "provider_metadata_json, created_at, updated_at, connected_at) VALUES "
                "(:c, :u, 'UPSTOX', :a, 1, 'connected', 'trading', 'inactive', 'inactive', '{}', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            if acct == "pending":
                stmt = text(stmt.text.replace("'connected'", "'pending'"))
            if acct == "UCC-9" and cid == "c2":
                with pytest.raises(Exception):
                    cx.execute(stmt, {"c": cid, "u": uid, "a": acct})
            else:
                cx.execute(stmt, {"c": cid, "u": uid, "a": acct})
        # both pending rows committed -> sentinel semantics preserved
        assert cx.execute(
            text("SELECT COUNT(*) FROM broker_connections WHERE broker_account_id = 'pending'")
        ).scalar() == 2


# ---------------------------------------------------------------------------
# Phase 22 item 14/18: no duplicate users; cleanup on failure
# ---------------------------------------------------------------------------
def test_callback_never_creates_users_any_scenario(client, db_session, monkeypatch):
    """Invariant sweep: across success and failure paths the user count
    never grows."""
    user = make_platform_user(db_session, email="a@example.com")
    n0 = counts(db_session)["users"]

    # success
    r1 = connect_flow(client, db_session, user, broker_profile("UCC-A", "a@upstox.example"), monkeypatch)
    assert r1.status_code == 307 and login_error_of(r1) == ""
    assert counts(db_session)["users"] == n0

    # reconnect attempt (credentials already stored)
    r2 = connect_flow(
        client, db_session, user, broker_profile("UCC-A", "a@upstox.example"), monkeypatch, store=False
    )
    assert r2.status_code == 307 and login_error_of(r2) == ""
    assert counts(db_session)["users"] == n0


def test_token_persisted_in_main_transaction(client, db_session, monkeypatch):
    """The BrokerToken row must exist in the SAME transaction as the
    connection (Phase 10): after a successful callback the DB already holds
    the encrypted token for the minted session."""
    user = make_platform_user(db_session, email="a@example.com")
    resp = connect_flow(client, db_session, user, broker_profile("UCC-A", "a@upstox.example"), monkeypatch)

    assert resp.status_code == 307
    conn = db_session.query(BrokerConnection).one()
    tok = db_session.query(BrokerToken).one()
    assert tok.connection_id == conn.id
    assert tok.broker_token_encrypted  # encrypted at rest
    assert tok.broker_token_encrypted != "upstox-access-token-value"  # never plaintext
    sess = db_session.query(UserSession).filter(
        UserSession.broker_connection_id == conn.id
    ).one()
    assert sess.session_hash == hash_session_id(resp.cookies.get("session_id"))
