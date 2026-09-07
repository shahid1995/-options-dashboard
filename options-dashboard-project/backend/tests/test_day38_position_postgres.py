"""Day 38 Task 4 — Position sequence allocation concurrency verification.

Test-only artifact. No production implementation change.
Real PostgreSQL (local test instance) — not SQLite, not Railway.
Uses independent connections/sessions with actual overlap (threading + barrier)
to verify the approved atomic ``position_sequence_anchor`` upsert semantics:

- same PositionIdentity concurrently -> unique, ordered, contiguous sequences
- different PositionIdentity values -> independent, no global contention
- rollback does not burn a sequence
- tenant isolation under concurrency
"""

import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Only run if a real PostgreSQL URL is configured (not SQLite).
DB_URL = os.getenv("TEST_DATABASE_URL", "")
if not DB_URL or not DB_URL.startswith(("postgresql+psycopg://", "postgresql://")):
    pytest.skip(
        "TEST_DATABASE_URL must point to PostgreSQL for concurrency verification",
        allow_module_level=True,
    )

ENGINE = create_engine(DB_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)
TestSession = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)

from app.trade_lifecycle.persistence import allocate_position_sequence  # noqa: E402
from app.db import Base  # noqa: E402


@pytest.fixture(scope="module")
def pg_tables():
    Base.metadata.create_all(bind=ENGINE)
    yield
    Base.metadata.drop_all(bind=ENGINE)


def _session():
    return TestSession()


def _alloc(db, *, tenant, user, symbol, expiry, strike, option_type):
    return allocate_position_sequence(
        db=db, tenant_id=tenant, user_id=user, symbol=symbol, expiry=expiry,
        strike=strike, option_type=option_type,
    )


def _concurrent_alloc(workers, alloc_fn):
    """Run alloc_fn(tid) in N threads released by a barrier; collect results."""
    barrier = threading.Barrier(workers)
    results = [None] * workers

    def run(tid):
        db = _session()
        try:
            barrier.wait()
            seq = alloc_fn(db, tid)
            db.commit()
            results[tid] = ("ok", seq)
        except Exception as e:  # pragma: no cover - surfaced via results
            db.rollback()
            results[tid] = ("err", repr(e))
        finally:
            db.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_concurrent_same_identity_allocates_unique_ordered_sequences(pg_tables):
    results = _concurrent_alloc(
        3,
        lambda db, tid: _alloc(
            db, tenant="t-seq", user="user-1", symbol="NIFTY",
            expiry="2026-12-31", strike=24000.0, option_type="CE",
        ),
    )
    assert all(r[0] == "ok" for r in results), f"all allocations must commit: {results}"
    seqs = sorted(r[1] for r in results)
    # Concurrent first-use must still produce exactly 1,2,3 with no duplicates.
    assert seqs == [1, 2, 3], f"expected unique ordered [1,2,3], got {seqs}"


def test_concurrent_different_identities_are_independent(pg_tables):
    def alloc_fn(db, tid):
        # Half the writers allocate identity A, half identity B.
        if tid % 2 == 0:
            return _alloc(db, tenant="t-ind", user="user-1", symbol="NIFTY",
                          expiry="2026-12-31", strike=24000.0, option_type="CE")
        return _alloc(db, tenant="t-ind", user="user-1", symbol="NIFTY",
                      expiry="2026-12-31", strike=25000.0, option_type="CE")

    results = _concurrent_alloc(4, alloc_fn)
    assert all(r[0] == "ok" for r in results), f"all allocations must commit: {results}"

    db = _session()
    rows = db.execute(
        text(
            "SELECT strike, last_position_sequence FROM position_sequence_anchor "
            "WHERE tenant_id = 't-ind' ORDER BY strike"
        )
    ).fetchall()
    db.close()
    by_strike = {float(strike): last for strike, last in rows}
    # Two writers per identity => each anchor ends at exactly 2, independently.
    assert by_strike.get(24000.0) == 2, f"identity A must be independent: {by_strike}"
    assert by_strike.get(25000.0) == 2, f"identity B must be independent: {by_strike}"


def test_rollback_does_not_burn_sequence_on_postgres(pg_tables):
    db = _session()
    first = _alloc(db, tenant="t-roll", user="user-1", symbol="NIFTY",
                   expiry="2026-12-31", strike=24000.0, option_type="CE")
    assert first == 1
    db.rollback()  # caller aborts: the anchor increment must not be burned

    again = _alloc(db, tenant="t-roll", user="user-1", symbol="NIFTY",
                   expiry="2026-12-31", strike=24000.0, option_type="CE")
    db.commit()
    assert again == 1, f"rollback must not burn a sequence, got {again}"
    db.close()


def test_concurrent_tenant_isolation_for_position_sequences(pg_tables):
    def alloc_fn(db, tid):
        tenant = "t-iso-A" if tid % 2 == 0 else "t-iso-B"
        return _alloc(db, tenant=tenant, user="user-1", symbol="NIFTY",
                      expiry="2026-12-31", strike=24000.0, option_type="CE")

    results = _concurrent_alloc(4, alloc_fn)
    assert all(r[0] == "ok" for r in results), f"all allocations must commit: {results}"

    db = _session()
    rows = db.execute(
        text(
            "SELECT tenant_id, last_position_sequence FROM position_sequence_anchor "
            "WHERE tenant_id IN ('t-iso-A','t-iso-B') ORDER BY tenant_id"
        )
    ).fetchall()
    db.close()
    by_tenant = {t: last for t, last in rows}
    # Two writers per tenant => each tenant's anchor is independent and ends at 2.
    assert by_tenant.get("t-iso-A") == 2, f"tenant A independent: {by_tenant}"
    assert by_tenant.get("t-iso-B") == 2, f"tenant B independent: {by_tenant}"
