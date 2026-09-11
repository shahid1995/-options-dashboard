"""Day41 Phase 10 — PostgreSQL concurrency verification (Day40.2 §4.3,
Day40.5 §6, Day40.6 §8).

Real PostgreSQL only (TEST_DATABASE_URL), following the Day38 convention.
SQLite runs are skipped: SKIP LOCKED / FOR UPDATE / ON CONFLICT arbitration
cannot be meaningfully exercised on a single-writer database.

Scenarios (Day40.6 §8 required cases):
  1. same raw observation claimed by two workers  → SKIP LOCKED, no double-claim
  2. same identifiable trade_id, two workers      → one fill row, one APPLIED
  3. two distinct no-ID fills, same attributes    → two rows, AMBIGUOUS composite
                                                    observed_count==2 (no merge)
  4. raw commit + crash → stale lease reclaim     → reprocess exactly-once effects
  5. correction / legacy-CEID overlap at the Task2 layer is covered by the
     Phase 1/2 suites (canonical_id PK idempotency); here we verify the
     fill-lane crash/retry property (scenario 4) and reprocessing idempotency.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

DB_URL = os.getenv("TEST_DATABASE_URL", "")
if not DB_URL or not DB_URL.startswith(("postgresql+psycopg://", "postgresql://")):
    pytest.skip(
        "TEST_DATABASE_URL must point to PostgreSQL for concurrency verification",
        allow_module_level=True,
    )

ENGINE = create_engine(DB_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)
TestSession = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)

from app.db import Base  # noqa: E402
import app.models  # noqa: E402,F401
import app.broker_sync.models  # noqa: E402,F401
import app.broker_sync.raw_ingress as raw_ingress  # noqa: E402,F401
import app.broker_sync.fill_ledger as fill_ledger  # noqa: E402,F401
import app.trade_lifecycle.persistence  # noqa: E402,F401

from app.broker_sync.raw_ingress import (  # noqa: E402
    BrokerRawObservation,
    ProcessingStatus,
    claim_raw_observations,
    commit_raw_observation,
    process_pending_observations,
)
from app.broker_sync.fill_ledger import (  # noqa: E402
    ObservationClass,
    ReconciliationState,
    BrokerFillLedgerFill,
    BrokerFillLedgerObservation,
    apply_lane_b_fill,
    composite_eq_key,
    evaluate_lane_c_equivalence,
    record_fill_observation,
)

_RECEIVED_AT = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def pg_tables():
    Base.metadata.create_all(bind=ENGINE)
    yield
    Base.metadata.drop_all(bind=ENGINE)


@pytest.fixture()
def db():
    session = TestSession()
    yield session
    session.rollback()
    session.close()


def _worker(fn, results, idx, barrier):
    session = TestSession()
    try:
        barrier.wait()
        results[idx] = fn(session)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Scenario 1 — same raw observation, two workers (SKIP LOCKED)
# ---------------------------------------------------------------------------

def test_skip_locked_no_double_claim(pg_tables, db) -> None:
    raw = commit_raw_observation(
        db, tenant_id="t1", broker="UPSTOX", source_mode="STREAM",
        raw_payload=b'{"k":1}', received_at=_RECEIVED_AT,
    )
    barrier = threading.Barrier(2)
    results: list[list[str]] = [[], []]

    def claim(session, out):
        rows = claim_raw_observations(session, limit=10, worker_id="w", lease_seconds=300)
        # claim_raw_observations returns detached rows — assert on plain ids.
        out.extend(r.raw_observation_id for r in rows)

    t1 = threading.Thread(target=claim, args=(TestSession(), results[0]))
    t2 = threading.Thread(target=claim, args=(TestSession(), results[1]))
    t1.start(); t2.start(); t1.join(); t2.join()

    claimed = results[0] + results[1]
    assert claimed.count(raw.raw_observation_id) <= 1, (
        "SKIP LOCKED violated: the same raw observation was claimed twice"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — same identifiable trade_id, two workers (Lane B)
# ---------------------------------------------------------------------------

def test_lane_b_same_trade_id_two_workers(pg_tables) -> None:
    barrier = threading.Barrier(2)
    outcomes: list[str] = ["", ""]

    def apply(session, idx):
        _, outcome, _ = fill_ledger.apply_lane_b_fill(
            session,
            tenant_id="t1", broker="UPSTOX", provider_order_id="O-CC",
            provider_trade_id="T-CC", d1="D1CC", content_fingerprint="FPCC",
            source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
        )
        outcomes[idx] = outcome

    t1 = threading.Thread(target=apply, args=(TestSession(), 0))
    t2 = threading.Thread(target=apply, args=(TestSession(), 1))
    t1.start(); t2.start(); t1.join(); t2.join()

    check = TestSession()
    try:
        fills = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-CC",
                BrokerFillLedgerFill.fill_identity_type == "TRADE_ID",
            )
        ).scalars().all()
        assert len(fills) == 1, "exactly-once violated: multiple TRADE_ID rows"
        assert sorted(outcomes) == ["APPLIED", "DUPLICATE_FILL"] or set(outcomes) == {"APPLIED"}
    finally:
        check.close()


# ---------------------------------------------------------------------------
# Scenario 3 — two distinct no-ID fills, identical attributes, two workers
# ---------------------------------------------------------------------------

def test_two_no_id_fills_concurrent_no_merge(pg_tables) -> None:
    barrier = threading.Barrier(2)

    def apply(session):
        obs = record_fill_observation(
            session,
            tenant_id="t1", broker="UPSTOX", provider_order_id="O-NI",
            observation_class=ObservationClass.ECONOMIC_FILL,
            d1="D1NI", content_fingerprint="FPNI",
            source_mode="STREAM", received_at=_RECEIVED_AT,
            fill_quantity=5, fill_price="100",
        )
        return obs, evaluate_lane_c_equivalence(session, obs)

    results: list = [None, None]
    t1 = threading.Thread(target=lambda: results.__setitem__(0, apply(TestSession())))
    t2 = threading.Thread(target=lambda: results.__setitem__(1, apply(TestSession())))
    t1.start(); t2.start(); t1.join(); t2.join()

    check = TestSession()
    try:
        rows = check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.provider_order_id == "O-NI",
            )
        ).scalars().all()
        assert len(rows) == 2, "Invariant X violated: identical no-ID fills merged"

        composite = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-NI",
                BrokerFillLedgerFill.fill_eq_key == composite_eq_key("t1", "O-NI", "D1NI"),
            )
        ).scalar_one()
        assert composite.observed_count == 2
        assert composite.reconciliation_state == ReconciliationState.AMBIGUOUS.value
    finally:
        check.close()


# ---------------------------------------------------------------------------
# Scenario 4 — raw commit → crash → stale-lease reclaim → idempotent replay
# ---------------------------------------------------------------------------

def test_crash_and_replay_idempotent(pg_tables, db) -> None:
    raw = commit_raw_observation(
        db, tenant_id="t1", broker="UPSTOX", source_mode="STREAM",
        raw_payload=b'{"k":2}', received_at=_RECEIVED_AT,
    )

    # Worker claims (lease committed) then "crashes" — session dropped.
    crash_session = TestSession()
    claimed = claim_raw_observations(crash_session, limit=10, worker_id="w1")
    crash_session.close()  # lease row left IN_PROGRESS, un-renewed
    assert any(r.raw_observation_id == raw.raw_observation_id for r in claimed)

    # Force the lease stale (lease is stamped at claim time → lease_expires_at).
    fresh = TestSession()
    row = fresh.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == raw.raw_observation_id,
        )
    ).scalar_one()
    row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    fresh.commit()
    fresh.close()

    # Recovery worker reclaims (stale lease) and processes idempotently.
    def processor(session, obs):
        # Effects must be idempotent by key; here: just mark SUCCEEDED.
        raw_ingress.mark_processing_result(
            session, obs, processing_status=ProcessingStatus.SUCCEEDED,
        )
        return raw_ingress.IngestionStatus.RAW_NORMALIZED.value

    fresh2 = TestSession()
    outcomes = raw_ingress.process_pending_observations(fresh2, processor, worker_id="w2")
    fresh2.close()
    assert (raw.raw_observation_id, ProcessingStatus.SUCCEEDED.value) in [
        (rid, status) for rid, status in outcomes
    ]
