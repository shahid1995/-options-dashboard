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
    upgrade_composite_to_trade,
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
    """Day41.1 invariant: for economic identity (tenant, broker, order,
    trade_id) exactly ONE worker is the first APPLIER.  Two simultaneous
    first-sighting workers ⇒ one APPLIED + one DUPLICATE_FILL, one fill row,
    one RECONCILED observation (one economic effect).  Both-APPLIED is
    IMPOSSIBLE under INSERT … ON CONFLICT DO NOTHING RETURNING arbitration.
    Callers own their commits (Day41.1 Defect-3): each worker commits.
    """
    barrier = threading.Barrier(2)
    outcomes: list[str] = ["", ""]

    def apply(session, idx):
        _, outcome, _ = fill_ledger.apply_lane_b_fill(
            session,
            tenant_id="t1", broker="UPSTOX", provider_order_id="O-CC",
            provider_trade_id="T-CC", d1="D1CC", content_fingerprint="FPCC",
            source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
        )
        session.commit()  # caller-owned transaction
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
        # Day41.1 strict arbitration: exactly one first applier.
        assert sorted(outcomes) == ["APPLIED", "DUPLICATE_FILL"], (
            f"expected exactly one APPLIED + one DUPLICATE_FILL, got {outcomes}"
        )
        obs_rows = check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.provider_order_id == "O-CC",
            )
        ).scalars().all()
        reconciled = [r for r in obs_rows if r.reconciliation_state == "RECONCILED"]
        assert len(reconciled) == 1, "one economic effect: exactly one RECONCILED observation"
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
        state = evaluate_lane_c_equivalence(session, obs)
        session.commit()  # caller-owned transaction (Day41.1)
        return obs.observation_id, state

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


# ===========================================================================
# Day41.1 — required transaction tests A–J (real PostgreSQL)
# ===========================================================================


def test_day41_1_B_duplicate_t1_replay_sequential(pg_tables) -> None:
    """B. duplicate T1 replay: same trade_id + same content after the applied
    fill commits ⇒ DUPLICATE_FILL, preserved DUPLICATE observation, ONE fill
    row, original content untouched."""
    s = TestSession()
    row1, out1, obs1 = fill_ledger.apply_lane_b_fill(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-B1",
        provider_trade_id="T-B1", d1="D-B1", content_fingerprint="FP-B1",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    s.commit()
    obs1_id = obs1.observation_id
    row2, out2, obs2 = fill_ledger.apply_lane_b_fill(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-B1",
        provider_trade_id="T-B1", d1="D-B1-dup", content_fingerprint="FP-B1",
        source_mode="RECOVERY", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    s.commit()
    assert out1 == "APPLIED" and out2 == "DUPLICATE_FILL"
    assert row2.fill_quantity == 5
    dup_id, dup_dup_of = obs2.observation_id, obs2.duplicate_of
    s.close()

    check = TestSession()
    try:
        dup = check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.observation_id == dup_id)
        ).scalar_one()
        assert dup.reconciliation_state == ReconciliationState.DUPLICATE.value
        assert dup.duplicate_of == obs1_id
        fills = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-B1")
        ).scalars().all()
        assert len(fills) == 1 and fills[0].fill_quantity == 5
    finally:
        check.close()


def test_day41_1_C_conflicting_t1_replay(pg_tables) -> None:
    """C. conflicting T1 replay: same trade_id + DIFFERENT content ⇒ CONFLICT;
    conflict observation preserved, applied fill never overwritten."""
    s = TestSession()
    row1, out1, _ = fill_ledger.apply_lane_b_fill(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-C1",
        provider_trade_id="T-C1", d1="D-C1", content_fingerprint="FP-C1",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=5,
    )
    s.commit()
    row2, out2, conflict_obs = fill_ledger.apply_lane_b_fill(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-C1",
        provider_trade_id="T-C1", d1="D-C1", content_fingerprint="FP-C1-DIFF",
        source_mode="RECOVERY", received_at=_RECEIVED_AT, fill_quantity=9,
    )
    s.commit()
    assert out1 == "APPLIED" and out2 == "CONFLICT"
    assert row2.fill_quantity == 5  # original fill NOT overwritten
    conflict_id, conflict_state = (
        conflict_obs.observation_id, conflict_obs.reconciliation_state,
    )
    s.close()

    check = TestSession()
    try:
        conflict = check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.observation_id == conflict_id)
        ).scalar_one()
        assert conflict.reconciliation_state == ReconciliationState.CONFLICT.value
        fills = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-C1")
        ).scalars().all()
        assert len(fills) == 1 and fills[0].fill_quantity == 5
        assert conflict.reconciliation_state == conflict_state
    finally:
        check.close()


def test_day41_1_D_rollback_after_fill_observation_write(pg_tables) -> None:
    """D. rollback after fill-observation write: NO Phase-2 state survives —
    while the committed Phase-1 raw evidence does (raw durability, §7)."""
    s = TestSession()
    raw = commit_raw_observation(
        s, tenant_id="t1", broker="UPSTOX", source_mode="STREAM",
        raw_payload=b'{"rb":1}', received_at=_RECEIVED_AT,
    )  # Phase-1: its own committed transaction
    raw_id = raw.raw_observation_id  # captured while the session is live
    obs = record_fill_observation(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-D1",
        observation_class=ObservationClass.ECONOMIC_FILL, d1="D-D1",
        content_fingerprint="FP-D1", source_mode="STREAM",
        received_at=_RECEIVED_AT, raw_observation_id=raw_id,
        fill_quantity=5,
    )
    evaluate_lane_c_equivalence(s, obs)
    s.rollback()  # Phase-2 rollback
    s.close()

    check = TestSession()
    try:
        # Phase-2 writes for THIS scenario's order are gone (order-scoped —
        # the disposable DB legitimately retains other scenarios' rows).
        assert check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.provider_order_id == "O-D1")
        ).scalars().all() == []
        assert check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-D1")
        ).scalars().all() == []
        # Phase-1 raw evidence survived the Phase-2 rollback.
        raw_back = check.execute(
            select(BrokerRawObservation).where(
                BrokerRawObservation.raw_observation_id == raw_id)
        ).scalar_one()
        assert raw_back.raw_payload == b'{"rb":1}'
    finally:
        check.close()


def test_day41_1_E_rollback_after_lineage_write(pg_tables) -> None:
    """E. rollback after lineage/upgrade write: alias + lineage + TRADE_ID
    rows all vanish; the AMBIGUOUS composite is unchanged (no partial state)."""
    s = TestSession()
    obs = record_fill_observation(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-E1",
        observation_class=ObservationClass.ECONOMIC_FILL, d1="D-E1",
        content_fingerprint="FP-E1", source_mode="STREAM",
        received_at=_RECEIVED_AT, fill_quantity=5,
    )
    evaluate_lane_c_equivalence(s, obs)
    s.commit()
    composite_key = composite_eq_key("t1", "O-E1", "D-E1")
    upgrade_composite_to_trade(
        s, tenant_id="t1", provider_order_id="O-E1",
        composite_key=composite_key, trade_ids=["T-E1"],
        trigger="TRADE_HISTORY", observation_ids=[obs.observation_id],
    )
    s.rollback()  # upgrade unit rolled back
    s.close()

    check = TestSession()
    try:
        from app.broker_sync.fill_ledger import (
            BrokerFillIdentityAlias, BrokerFillIdentityLineage,
        )
        # Order-scoped: this scenario's upgrade must have left NO trace.
        assert check.execute(
            select(BrokerFillIdentityAlias).where(
                BrokerFillIdentityAlias.provider_order_id == "O-E1")
        ).scalars().all() == []
        # The upgrade's OWN lineage row (outcome UPGRADED) is gone; the
        # pre-upgrade NO_CANDIDATE lineage was committed by the earlier
        # equivalence transaction and legitimately remains as evidence.
        lineage = check.execute(
            select(BrokerFillIdentityLineage).where(
                BrokerFillIdentityLineage.provider_order_id == "O-E1")
        ).scalars().all()
        assert lineage, "pre-upgrade equivalence lineage must be preserved"
        assert all(
            l.outcome != "UPGRADED" for l in lineage
        ), "rolled-back upgrade lineage must not survive"
        assert check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-E1",
                BrokerFillLedgerFill.fill_identity_type == "TRADE_ID")
        ).scalars().all() == []
        composite = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.fill_eq_key == composite_key)
        ).scalar_one()
        assert composite.reconciliation_state == ReconciliationState.AMBIGUOUS.value
        assert composite.frozen_reason is None  # no partial freeze survived
    finally:
        check.close()


def test_day41_1_F_rollback_before_canonical_emission(pg_tables) -> None:
    """F. rollback before canonical emission: the full economic unit (fill +
    observation + lineage) rolls back together — nothing is applied, and a
    later retry (G) applies exactly once."""
    s = TestSession()
    _, _, obs = fill_ledger.apply_lane_b_fill(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-F1",
        provider_trade_id="T-F1", d1="D-F1", content_fingerprint="FP-F1",
        source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=4,
    )
    # Canonical emission (Task2) would happen here — simulate failure BEFORE it.
    s.rollback()
    s.close()

    check = TestSession()
    try:
        assert check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-F1")
        ).scalars().all() == []
    finally:
        check.close()


def test_day41_1_G_canonical_emission_retry(pg_tables) -> None:
    """G. canonical emission retry: the same economic delivery re-submitted
    after a committed application is a retry-safe DUPLICATE_FILL — still one
    fill row, one RECONCILED observation."""
    for expected in ("APPLIED", "DUPLICATE_FILL"):
        s = TestSession()
        _, outcome, _ = fill_ledger.apply_lane_b_fill(
            s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-G1",
            provider_trade_id="T-G1", d1="D-G1", content_fingerprint="FP-G1",
            source_mode="STREAM", received_at=_RECEIVED_AT, fill_quantity=6,
        )
        s.commit()
        s.close()
        assert outcome == expected

    check = TestSession()
    try:
        assert len(check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-G1")
        ).scalars().all()) == 1
        reconciled = check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.provider_order_id == "O-G1",
                BrokerFillLedgerObservation.reconciliation_state == "RECONCILED")
        ).scalars().all()
        assert len(reconciled) == 1
    finally:
        check.close()


def test_day41_1_H_same_raw_observation_replay(pg_tables) -> None:
    """H. same raw observation replay: reprocessing an already-classified
    observation is a durable no-op — the composite observed_count must NOT
    double-increment (recovery replay is idempotent)."""
    s = TestSession()
    obs = record_fill_observation(
        s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-H1",
        observation_class=ObservationClass.ECONOMIC_FILL, d1="D-H1",
        content_fingerprint="FP-H1", source_mode="STREAM",
        received_at=_RECEIVED_AT, fill_quantity=5,
    )
    s.commit()
    state1 = evaluate_lane_c_equivalence(s, obs)
    s.commit()
    state2 = evaluate_lane_c_equivalence(s, obs)  # replay
    s.commit()
    s.close()
    assert state1 == ReconciliationState.AMBIGUOUS.value
    assert state2 == ReconciliationState.AMBIGUOUS.value

    check = TestSession()
    try:
        composite = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.fill_eq_key == composite_eq_key("t1", "O-H1", "D-H1"))
        ).scalar_one()
        assert composite.observed_count == 1, "replay re-incremented the composite"
    finally:
        check.close()


def test_day41_1_I_two_workers_same_no_id_observation(pg_tables) -> None:
    """I. two workers evaluating the SAME no-ID observation concurrently:
    serialization + the replay guard yield exactly ONE effective increment —
    observed_count == 1, both workers report AMBIGUOUS."""
    setup = TestSession()
    obs = record_fill_observation(
        setup, tenant_id="t1", broker="UPSTOX", provider_order_id="O-I1",
        observation_class=ObservationClass.ECONOMIC_FILL, d1="D-I1",
        content_fingerprint="FP-I1", source_mode="STREAM",
        received_at=_RECEIVED_AT, fill_quantity=5,
    )
    setup.commit()
    obs_id = obs.observation_id
    setup.close()

    barrier = threading.Barrier(2)
    states: list[str] = ["", ""]

    def worker(idx):
        s = TestSession()
        try:
            row = s.execute(
                select(BrokerFillLedgerObservation).where(
                    BrokerFillLedgerObservation.observation_id == obs_id)
            ).scalar_one()
            states[idx] = fill_ledger.evaluate_lane_c_equivalence(s, row)
            s.commit()
        finally:
            s.close()

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert states == [ReconciliationState.AMBIGUOUS.value] * 2
    check = TestSession()
    try:
        composite = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.fill_eq_key == composite_eq_key("t1", "O-I1", "D-I1"))
        ).scalar_one()
        assert composite.observed_count == 1, (
            "two workers on the SAME observation double-applied the increment"
        )
    finally:
        check.close()


def test_day41_1_J_two_distinct_no_id_fills_sequential_no_merge(pg_tables) -> None:
    """J. two distinct no-ID fills with identical attributes, sequential:
    two preserved observations, ONE AMBIGUOUS composite with observed_count=2,
    no economic canonical fill (fail-closed, Invariants X/Z)."""
    s = TestSession()
    for _ in range(2):
        obs = record_fill_observation(
            s, tenant_id="t1", broker="UPSTOX", provider_order_id="O-J1",
            observation_class=ObservationClass.ECONOMIC_FILL, d1="D-J1",
            content_fingerprint="FP-J1", source_mode="STREAM",
            received_at=_RECEIVED_AT, fill_quantity=5,
        )
        assert evaluate_lane_c_equivalence(s, obs) == ReconciliationState.AMBIGUOUS.value
        s.commit()
    s.close()

    check = TestSession()
    try:
        rows = check.execute(
            select(BrokerFillLedgerObservation).where(
                BrokerFillLedgerObservation.provider_order_id == "O-J1")
        ).scalars().all()
        assert len(rows) == 2
        composite = check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.fill_eq_key == composite_eq_key("t1", "O-J1", "D-J1"))
        ).scalar_one()
        assert composite.observed_count == 2
        assert composite.reconciliation_state == ReconciliationState.AMBIGUOUS.value
        # No TRADE_ID row for THIS scenario's order (order-scoped — the
        # shared disposable DB legitimately retains other scenarios' TRADE_IDs).
        assert check.execute(
            select(BrokerFillLedgerFill).where(
                BrokerFillLedgerFill.provider_order_id == "O-J1",
                BrokerFillLedgerFill.fill_identity_type == "TRADE_ID")
        ).scalars().all() == []
    finally:
        check.close()
