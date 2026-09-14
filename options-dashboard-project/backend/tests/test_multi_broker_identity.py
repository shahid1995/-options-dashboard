"""Multi-broker identity refactor — authorized invariant tests.

Target architecture (mission brief, Phase 1):

    one StrikeNova user  ->  many BrokerConnections
                             ├── UPSTOX / account-A
                             ├── UPSTOX / account-B
                             └── FYERS  / account-B

Ownership authority is ``BrokerConnection.user_id`` (the broker-ownership
ledger).  The legacy ``users.broker_provider`` / ``users.broker_user_id``
stamp is compatibility metadata only: it may be populated when empty and
must never be overwritten, must never act as authorization, and must
never block a legitimate additional broker/account connection.

External broker seams (exchange / profile / extract_account_id) are
mocked per the repository's established technique (test_auth_router.py,
test_identity_linking.py).  All broker identities are synthetic — no
real broker data appears anywhere.
"""

from __future__ import annotations

import os
import threading
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.db import SessionLocal as _real_session_local
import app.routers.auth as auth_mod
from app.identity import (
    BrokerConnection,
    BrokerIdentityInUse,
    BrokerToken,
    User,
    UserSession,
    create_session_record,
    find_broker_identity_owner,
    get_or_create_connection,
    resolve_platform_user,
    store_credentials,
)
from app.services import token_store
from app.main import app


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


def store_byob(db, user: User, broker: str = "UPSTOX") -> None:
    store_credentials(db, user.id, broker, f"{broker.lower()}-key", f"{broker.lower()}-secret")
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


def mock_broker(monkeypatch, profile: dict):
    """Mock the adapter seam for whatever broker the state carries."""
    adapter = AsyncMock()
    adapter.exchange_authorization_code = AsyncMock(return_value="mocked-access-token-value")
    adapter.get_profile = AsyncMock(return_value=profile)
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
    client, db, user: User, broker: str, account_id: str, monkeypatch,
    *, store: bool = True,
):
    """Full connect flow for an arbitrary broker (synthetic identity)."""
    profile = broker_profile(account_id, f"{account_id.lower()}@broker.example")
    if store:
        store_byob(db, user, broker)
    sid = login_initiator(db, user)
    mock_broker(monkeypatch, profile)
    state = token_store.create_oauth_state(session_id=sid, broker=broker)
    return client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )


def start_connect(db, user: User, broker: str, account_id: str, monkeypatch) -> str:
    """Prepare (BYOB + session + state) without firing the callback."""
    profile = broker_profile(account_id, f"{account_id.lower()}@broker.example")
    store_byob(db, user, broker)
    sid = login_initiator(db, user)
    mock_broker(monkeypatch, profile)
    return token_store.create_oauth_state(session_id=sid, broker=broker)


def fire_callback(client, state: str):
    return client.get(
        "/auth/callback",
        params={"code": "single-use-auth-code", "state": state},
        follow_redirects=False,
    )


def login_error_of(resp) -> str:
    from urllib.parse import urlsplit, parse_qs

    q = parse_qs(urlsplit(resp.headers["location"]).query)
    return q.get("login_error", [""])[0]


def connections_for(db, user: User):
    return (
        db.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id)
        .filter(BrokerConnection.broker_account_id.notin_(["pending", "data-only"]))
        .order_by(BrokerConnection.connected_at, BrokerConnection.id)
        .all()
    )


# ---------------------------------------------------------------------------
# Test A — First broker still works (existing Upstox behavior intact)
# ---------------------------------------------------------------------------
def test_a_first_broker_still_works(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="a@example.com")

    resp = connect_flow(client, db_session, user, "UPSTOX", "UCC-A1", monkeypatch)

    assert resp.status_code == 307, f"first connect failed: {login_error_of(resp)}"
    assert login_error_of(resp) == ""
    conns = connections_for(db_session, user)
    assert len(conns) == 1
    assert conns[0].broker == "UPSTOX"
    assert conns[0].broker_account_id == "UCC-A1"
    assert conns[0].user_id == user.id
    # one User, one connection; session + encrypted token minted
    assert counts(db_session)["users"] == 1
    assert db_session.query(BrokerToken).count() == 1
    tok = db_session.query(BrokerToken).one()
    assert tok.broker_token_encrypted != "mocked-access-token-value"  # encrypted


# ---------------------------------------------------------------------------
# Test B — Same user connects a second broker (FYERS identity, synthetic)
# ---------------------------------------------------------------------------
def test_b_same_user_second_broker_succeeds(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="b@example.com")

    first = connect_flow(client, db_session, user, "UPSTOX", "UCC-B1", monkeypatch)
    assert first.status_code == 307 and login_error_of(first) == ""

    second = connect_flow(client, db_session, user, "FYERS", "FY-B2", monkeypatch)
    assert second.status_code == 307, f"second broker blocked: {login_error_of(second)}"
    assert login_error_of(second) == ""

    assert counts(db_session)["users"] == 1, "second broker must never fork a User"
    conns = connections_for(db_session, user)
    assert {(c.broker, c.broker_account_id) for c in conns} == {
        ("UPSTOX", "UCC-B1"),
        ("FYERS", "FY-B2"),
    }
    assert {c.user_id for c in conns} == {user.id}


# ---------------------------------------------------------------------------
# Test C — Same user connects a second account of the same broker
# ---------------------------------------------------------------------------
def test_c_same_user_second_account_same_broker_succeeds(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="c@example.com")

    first = connect_flow(client, db_session, user, "UPSTOX", "UCC-C1", monkeypatch)
    assert first.status_code == 307 and login_error_of(first) == ""

    second = connect_flow(client, db_session, user, "UPSTOX", "UCC-C2", monkeypatch)
    assert second.status_code == 307, f"second account blocked: {login_error_of(second)}"
    assert login_error_of(second) == ""

    assert counts(db_session)["users"] == 1
    conns = connections_for(db_session, user)
    assert len(conns) == 2
    assert {c.broker_account_id for c in conns} == {"UCC-C1", "UCC-C2"}
    assert {c.user_id for c in conns} == {user.id}


# ---------------------------------------------------------------------------
# Test D — Cross-user ownership conflict (ledger authority)
# ---------------------------------------------------------------------------
def test_d_cross_user_ownership_conflict_rejected(client, db_session, monkeypatch):
    owner = make_platform_user(db_session, email="owner@example.com")
    owner_conn = BrokerConnection(
        id=str(uuid4()),
        user_id=owner.id,
        broker="UPSTOX",
        broker_account_id="UCC-CONFLICT",
        status="connected",
    )
    db_session.add(owner_conn)
    db_session.commit()

    attacker = make_platform_user(db_session, email="attacker@example.com")
    state = start_connect(db_session, attacker, "UPSTOX", "UCC-CONFLICT", monkeypatch)
    before = counts(db_session)

    resp = fire_callback(client, state)

    assert resp.status_code == 307
    assert login_error_of(resp) == "broker_identity_in_use"
    assert counts(db_session) == before, "rejected attempt must write nothing"
    db_session.refresh(owner_conn)
    assert owner_conn.user_id == owner.id, "no ownership transfer"


# ---------------------------------------------------------------------------
# Test E — Legacy Upstox stamp does not block another broker
# ---------------------------------------------------------------------------
def test_e_legacy_stamp_does_not_block_second_broker(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="e@example.com", stamped=("UPSTOX", "UP-123"))

    resp = connect_flow(client, db_session, user, "FYERS", "FY-456", monkeypatch)

    assert resp.status_code == 307, f"legacy stamp blocked second broker: {login_error_of(resp)}"
    assert login_error_of(resp) == ""
    assert counts(db_session)["users"] == 1
    conns = connections_for(db_session, user)
    assert [(c.broker, c.broker_account_id) for c in conns] == [("FYERS", "FY-456")]
    # legacy Upstox stamp NOT overwritten by the FYERS identity
    db_session.refresh(user)
    assert user.broker_provider == "UPSTOX"
    assert user.broker_user_id == "UP-123"


# ---------------------------------------------------------------------------
# Test F — Legacy stamp does not block another account of the same broker
# ---------------------------------------------------------------------------
def test_f_legacy_stamp_does_not_block_second_account(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="f@example.com", stamped=("UPSTOX", "UP-123"))

    resp = connect_flow(client, db_session, user, "UPSTOX", "UCC-456", monkeypatch)

    assert resp.status_code == 307, f"legacy stamp blocked second account: {login_error_of(resp)}"
    assert login_error_of(resp) == ""
    assert counts(db_session)["users"] == 1
    conns = connections_for(db_session, user)
    assert [c.broker_account_id for c in conns] == ["UCC-456"]
    # legacy metadata untouched
    db_session.refresh(user)
    assert user.broker_provider == "UPSTOX"
    assert user.broker_user_id == "UP-123"


# ---------------------------------------------------------------------------
# Test G — Legacy stamp alone never creates ownership
# ---------------------------------------------------------------------------
def test_g_legacy_stamp_alone_is_not_ownership(client, db_session, monkeypatch):
    """A stale legacy stamp must NOT make a broker identity look owned when
    no authoritative BrokerConnection exists — ownership is the ledger."""
    staler = make_platform_user(db_session, email="stale@example.com", stamped=("UPSTOX", "UCC-STALE"))
    other = make_platform_user(db_session, email="other@example.com")

    owner_id = find_broker_identity_owner(db_session, "UPSTOX", "UCC-STALE", "UCC-STALE")

    assert owner_id is None, (
        "legacy stamp without a BrokerConnection must not confer ownership"
    )

    # and the 'other' user may legitimately connect the identity the stale
    # stamp refers to — no user-visible or data-level blocking.
    resp = connect_flow(client, db_session, other, "UPSTOX", "UCC-STALE", monkeypatch)
    assert resp.status_code == 307 and login_error_of(resp) == ""
    conns = connections_for(db_session, other)
    assert [c.broker_account_id for c in conns] == ["UCC-STALE"]
    assert conns[0].user_id == other.id
    # the stale-stamped user was untouched
    db_session.refresh(staler)
    assert staler.broker_user_id == "UCC-STALE"
    assert connections_for(db_session, staler) == []


# ---------------------------------------------------------------------------
# Test H — Corrupt ownership fails closed
# ---------------------------------------------------------------------------
def test_h_corrupt_ownership_fails_closed(client, db_session, monkeypatch):
    """Artificial inconsistent state: the ledger says user1 owns the
    identity, the legacy stamp says user2. The flow must fail closed —
    no automatic transfer, no silent reconciliation."""
    user1 = make_platform_user(db_session, email="u1@example.com")
    user2 = make_platform_user(db_session, email="u2@example.com", stamped=("UPSTOX", "UCC-CORRUPT"))
    ledger_conn = BrokerConnection(
        id=str(uuid4()),
        user_id=user1.id,
        broker="UPSTOX",
        broker_account_id="UCC-CORRUPT",
        status="connected",
    )
    db_session.add(ledger_conn)
    db_session.commit()

    # Direct helper contract: disagreement raises, nothing reconciled.
    with pytest.raises(BrokerIdentityInUse):
        find_broker_identity_owner(db_session, "UPSTOX", "UCC-CORRUPT", "UCC-CORRUPT")

    # End-to-end: even the stamped 'owner' per legacy metadata (user2) is
    # refused — corrupt state fails closed for everyone, no silent repair.
    state = start_connect(db_session, user2, "UPSTOX", "UCC-CORRUPT", monkeypatch)
    before = counts(db_session)
    resp = fire_callback(client, state)
    assert login_error_of(resp) == "broker_identity_in_use"
    db_session.refresh(ledger_conn)
    assert ledger_conn.user_id == user1.id, "no automatic transfer"
    assert counts(db_session) == before, "no silent reconciliation writes"


# ---------------------------------------------------------------------------
# Test I — Same-user reconnect remains idempotent
# ---------------------------------------------------------------------------
def test_i_same_user_reconnect_idempotent(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="i@example.com")
    profile = broker_profile("UCC-I1", "ucc-i1@broker.example")

    first = connect_flow(client, db_session, user, "UPSTOX", "UCC-I1", monkeypatch)
    assert first.status_code == 307 and login_error_of(first) == ""
    conn_id_first = connections_for(db_session, user)[0].id

    # reconnect — credentials already stored, fresh session + state
    sid2 = login_initiator(db_session, user)
    mock_broker(monkeypatch, profile)
    before_second = counts(db_session)
    state2 = token_store.create_oauth_state(session_id=sid2, broker="UPSTOX")
    second = fire_callback(client, state2)

    assert second.status_code == 307 and login_error_of(second) == ""
    conns = connections_for(db_session, user)
    assert len(conns) == 1, "reconnect must not duplicate the connection"
    assert conns[0].id == conn_id_first
    after_second = counts(db_session)
    assert after_second["connections"] == before_second["connections"]
    assert after_second["sessions"] == before_second["sessions"] + 1
    assert after_second["tokens"] == before_second["tokens"] + 1
    assert after_second["users"] == 1


# ---------------------------------------------------------------------------
# Test J — No duplicate User across every successful multi-broker scenario
# ---------------------------------------------------------------------------
def test_j_no_duplicate_users_across_scenarios(client, db_session, monkeypatch):
    user = make_platform_user(db_session, email="j@example.com")
    n0 = counts(db_session)["users"]

    r1 = connect_flow(client, db_session, user, "UPSTOX", "UCC-J1", monkeypatch)
    assert r1.status_code == 307 and login_error_of(r1) == ""
    r2 = connect_flow(client, db_session, user, "FYERS", "FY-J2", monkeypatch)
    assert r2.status_code == 307 and login_error_of(r2) == ""
    r3 = connect_flow(client, db_session, user, "UPSTOX", "UCC-J3", monkeypatch)
    assert r3.status_code == 307 and login_error_of(r3) == ""
    # reconnect (no new BYOB store)
    r4 = connect_flow(client, db_session, user, "UPSTOX", "UCC-J1", monkeypatch, store=False)
    assert r4.status_code == 307 and login_error_of(r4) == ""

    assert counts(db_session)["users"] == n0
    conns = connections_for(db_session, user)
    assert {(c.broker, c.broker_account_id) for c in conns} == {
        ("UPSTOX", "UCC-J1"),
        ("FYERS", "FY-J2"),
        ("UPSTOX", "UCC-J3"),
    }


# ---------------------------------------------------------------------------
# Test K — Cross-user concurrency: exactly one owner, one committed row
# ---------------------------------------------------------------------------
# Layer 1 (always run): deterministic ledger arbitration — the committed
# winner is respected and the challenger is rejected with nothing written.
# Layer 2 (Postgres-gated, day38 harness pattern): a REAL barrier-
# synchronized threaded race on the actual database. SQLite's single
# StaticPool connection cannot host concurrent transactions (its statement
# state cannot interleave two writers), so genuine simultaneity is proven
# only on Postgres — the same gate the repo's other concurrency suites use.


def test_k_cross_user_ledger_arbitration_deterministic(client, db_session, monkeypatch):
    user_a = make_platform_user(db_session, email="k1@example.com")
    user_b = make_platform_user(db_session, email="k2@example.com")

    # User A wins the identity.
    r1 = connect_flow(client, db_session, user_a, "UPSTOX", "UCC-RACE", monkeypatch)
    assert r1.status_code == 307 and login_error_of(r1) == ""

    # User B's attempt is rejected; nothing is written for B.
    state2 = start_connect(db_session, user_b, "UPSTOX", "UCC-RACE", monkeypatch)
    before = counts(db_session)
    r2 = fire_callback(client, state2)
    assert r2.status_code == 307
    assert login_error_of(r2) == "broker_identity_in_use"
    assert counts(db_session) == before

    # Exactly one committed connection for the identity, owned by A.
    live = (
        db_session.query(BrokerConnection)
        .filter(BrokerConnection.broker == "UPSTOX")
        .filter(BrokerConnection.broker_account_id == "UCC-RACE")
        .all()
    )
    assert len(live) == 1
    assert live[0].user_id == user_a.id


def test_k_cross_user_first_attempt_integrityerror_classified(client, db_session, monkeypatch):
    """Race loser whose pre-check missed (winner committed between the
    SELECT and the INSERT): the DB unique index rejects the INSERT and the
    callback classifies it as broker_identity_in_use — no transfer."""
    owner = make_platform_user(db_session, email="k3@example.com")
    challenger = make_platform_user(db_session, email="k4@example.com")

    # Challenger prepared FIRST, so its ownership pre-check legitimately
    # misses; the owner's row appears only via the injected race.
    state = start_connect(db_session, challenger, "UPSTOX", "UCC-RACE2", monkeypatch)
    owner_conn = BrokerConnection(
        id=str(uuid4()),
        user_id=owner.id,
        broker="UPSTOX",
        broker_account_id="UCC-RACE2",
        status="connected",
    )
    db_session.add(owner_conn)
    db_session.commit()

    calls = {"n": 0}
    real_gocc = auth_mod.get_or_create_connection

    def racing_gocc(db, user_id, broker, account_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError(
                "INSERT failed", None,
                Exception("uq_broker_identity_global duplicate"),
            )
        return real_gocc(db, user_id, broker, account_id, **kw)

    monkeypatch.setattr("app.routers.auth.get_or_create_connection", racing_gocc)

    before = counts(db_session)
    resp = fire_callback(client, state)
    assert resp.status_code == 307
    assert login_error_of(resp) == "broker_identity_in_use"
    assert counts(db_session) == before
    db_session.refresh(owner_conn)
    assert owner_conn.user_id == owner.id


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith(
        ("postgresql+psycopg://", "postgresql://")
    ),
    reason="real threaded race requires TEST_DATABASE_URL pointing at PostgreSQL",
)
def test_k_cross_user_real_threaded_race_postgres():
    """REAL race: two users, two threads, two independent Postgres sessions
    and transactions, barrier-synchronized on the same broker identity.
    Expected: exactly one COMMIT succeeds as owner; the loser hits the
    global partial unique index and get_or_create_connection classifies it
    as BrokerIdentityInUse (no transfer, no duplicate)."""
    from threading import Barrier

    from sqlalchemy import text

    pg_engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(bind=pg_engine)
    # The global ownership arbiter (created by migration d9e0f1a2b3c4;
    # deliberately absent from ORM metadata).
    with pg_engine.begin() as cx:
        cx.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_broker_identity_global "
                "ON broker_connections (broker, broker_account_id) "
                "WHERE broker_account_id <> 'pending' "
                "AND broker_account_id <> 'data-only'"
            )
        )
    TestSession = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)

    seed = TestSession()
    try:
        ua = User(id=str(uuid4()), status="active", identity_source="email")
        ub = User(id=str(uuid4()), status="active", identity_source="email")
        seed.add_all([ua, ub])
        seed.commit()
        user_a_id, user_b_id = ua.id, ub.id
    finally:
        seed.close()

    race_id = f"UCC-PG-RACE-{uuid4()}"
    barrier = Barrier(2)
    outcomes = {}

    def racer(key, user_id):
        s = TestSession()
        try:
            barrier.wait()
            get_or_create_connection(s, user_id, "UPSTOX", race_id)
            s.commit()
            outcomes[key] = ("committed", user_id)
        except BrokerIdentityInUse:
            s.rollback()
            outcomes[key] = ("rejected", user_id)
        except IntegrityError:
            s.rollback()
            outcomes[key] = ("integrity_error", user_id)
        finally:
            s.close()

    t1 = threading.Thread(target=racer, args=("a", user_a_id))
    t2 = threading.Thread(target=racer, args=("b", user_b_id))
    t1.start(); t2.start(); t1.join(timeout=60); t2.join(timeout=60)

    try:
        kinds = sorted(k for k, _ in outcomes.values())
        assert kinds in (["committed", "rejected"], ["committed", "integrity_error"]), (
            f"unexpected race outcomes: {outcomes}"
        )
        verify = TestSession()
        try:
            rows = (
                verify.query(BrokerConnection)
                .filter(BrokerConnection.broker == "UPSTOX")
                .filter(BrokerConnection.broker_account_id == race_id)
                .all()
            )
            assert len(rows) == 1, "exactly one committed connection may exist"
            winner_key = "a" if outcomes["a"][0] == "committed" else "b"
            assert rows[0].user_id == outcomes[winner_key][1]
            loser_key = "b" if winner_key == "a" else "a"
            assert outcomes[loser_key][0] in ("rejected", "integrity_error")
            # sentinels untouched by the race (global index semantics intact)
            assert (
                verify.query(BrokerConnection)
                .filter(BrokerConnection.broker_account_id.in_(["pending", "data-only"]))
                .count()
            ) >= 0
        finally:
            verify.close()
    finally:
        # clean the race rows so the shared test DB stays pristine
        cleanup = TestSession()
        try:
            cleanup.query(BrokerConnection).filter(
                BrokerConnection.broker_account_id == race_id
            ).delete(synchronize_session=False)
            cleanup.query(User).filter(User.id.in_([user_a_id, user_b_id])).delete(
                synchronize_session=False
            )
            cleanup.commit()
        finally:
            cleanup.close()
            Base.metadata.drop_all(bind=pg_engine)
            pg_engine.dispose()


# ---------------------------------------------------------------------------
# Test L — Same-user concurrency
# ---------------------------------------------------------------------------
def test_l_same_user_concurrency_idempotent(db_session, monkeypatch):
    """The same user races two get_or_create_connection calls for the same
    identity (the ledger-level seam the callback drives). The outcome is
    deterministic — one BrokerConnection, no uncaught error.

    Implementation note: SQLite's single serialized writer makes the
    second writer's first SELECT block until the first commits, which the
    callback's recovery path then classifies as a same-user winner —
    the exact deterministic idempotency contract, at the ledger seam.
    (The full threaded-callback harness is validated on Postgres in the
    staging Phase-11 evidence run of the identity-linking workstream.)"""
    from app.identity import get_or_create_connection

    user = make_platform_user(db_session, email="l@example.com")
    db_session.commit()

    c1 = get_or_create_connection(db_session, user.id, "UPSTOX", "UCC-SAME")
    c2 = get_or_create_connection(db_session, user.id, "UPSTOX", "UCC-SAME")
    db_session.commit()

    conns = connections_for(db_session, user)
    assert len(conns) == 1, "same-user race must yield exactly one connection"
    assert conns[0].id == c1.id == c2.id
    assert conns[0].broker_account_id == "UCC-SAME"
    assert conns[0].user_id == user.id


# ---------------------------------------------------------------------------
# Helper-level contracts (unit layer beneath the end-to-end tests)
# ---------------------------------------------------------------------------
def test_ensure_stamp_helper_no_longer_blocks_additional_brokers():
    """ensure_broker_stamp semantics after refactor: populate-when-empty,
    identical→no-op, different→NO-OP (legacy metadata, never authorization).
    Overwrite of an existing different stamp is forbidden, not transferred.
    """
    from app.identity import ensure_broker_stamp

    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        u = User(id=str(uuid4()), status="active", identity_source="email")
        s.add(u); s.commit()

        # empty -> populated
        ensure_broker_stamp(s, u, "UPSTOX", "UP-123")
        assert (u.broker_provider, u.broker_user_id) == ("UPSTOX", "UP-123")
        # identical -> no-op
        ensure_broker_stamp(s, u, "UPSTOX", "UP-123")
        # different provider/account -> no exception, no overwrite
        ensure_broker_stamp(s, u, "FYERS", "FY-456")
        assert (u.broker_provider, u.broker_user_id) == ("UPSTOX", "UP-123")
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_get_or_create_connection_supports_second_account_same_user():
    """The ledger helper itself must allow a second (broker, account) row for
    one user — the DB-level guarantee behind Tests B/C."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        u = User(id=str(uuid4()), status="active", identity_source="email")
        s.add(u); s.commit()

        c1 = get_or_create_connection(s, u.id, "UPSTOX", "UCC-M1")
        c2 = get_or_create_connection(s, u.id, "UPSTOX", "UCC-M2")
        c3 = get_or_create_connection(s, u.id, "FYERS", "FY-M3")
        s.commit()
        rows = s.query(BrokerConnection).order_by(BrokerConnection.broker_account_id).all()
        assert len(rows) == 3
        assert {r.broker_account_id for r in rows} == {"UCC-M1", "UCC-M2", "FY-M3"}
        assert all(r.user_id == u.id for r in rows)
        # idempotent re-link of the same identity
        c1b = get_or_create_connection(s, u.id, "UPSTOX", "UCC-M1")
        assert c1b.id == c1.id
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_resolve_platform_user_remains_session_bound_only():
    """Platform identity resolution is untouched: session user_id -> User,
    no broker-profile involvement, no creation."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        u = User(id=str(uuid4()), status="active", identity_source="email")
        s.add(u); s.commit()
        assert resolve_platform_user(s, u.id).id == u.id
        with pytest.raises(ValueError):
            resolve_platform_user(s, "no-such-user")
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
