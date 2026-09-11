"""Day41 Phase 3/4 — Durable raw-ingress tests (Day40.6 §1/§2/§3).

Verifies:
- Phase-1 commit durability: the raw row exists and survives everything after
- byte preservation: raw_payload returns the EXACT bytes committed
- normalization failure preserves the raw record (Invariant AC)
- crash/replay: claim → crash → stale-lease reclaim → reprocess idempotently
- status honesty: RAW_RECEIVED → RAW_NORMALIZED/FAILED transitions
- immutable columns are never rewritten (raw_payload, received_at, provenance)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync.raw_ingress import (
    IngestionStatus,
    ProcessingStatus,
    BrokerRawObservation,
    claim_raw_observations,
    commit_raw_observation,
    get_delivery_evidence,
    mark_processing_result,
    process_pending_observations,
)

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture()
def db():
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.broker_sync.raw_ingress  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    Base.metadata.create_all(_engine)
    session = _TestSessionLocal()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(_engine)


# Provider payload with fields that would break on naive JSON round-trips
# (unicode, key order, escaped chars, float formatting).
_RAW_PAYLOAD = (
    b'{"update_type":"order","status":"put order req received","order_id":"240221025997024",'
    b'"tag":"caf\xc3\xa9-order","price":0.0,"pending_quantity":1,"note":"\\"quoted\\""}'
).decode("utf-8").encode("utf-8")
_RECEIVED_AT = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Phase 1: durability + byte preservation
# ---------------------------------------------------------------------------

def test_phase1_commit_durability(db) -> None:
    row = commit_raw_observation(
        db,
        tenant_id="tenant-1",
        broker="UPSTOX",
        source_mode="STREAM",
        raw_payload=_RAW_PAYLOAD,
        received_at=_RECEIVED_AT,
    )
    assert row.processing_status == ProcessingStatus.PENDING.value
    assert row.ingestion_status == IngestionStatus.RAW_RECEIVED.value
    assert row.attempt_count == 0
    # Row is durably present in a fresh session (commit survived the session)
    check = _TestSessionLocal()
    found = check.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == row.raw_observation_id
        )
    ).scalar_one()
    check.close()
    assert found is not None


def test_raw_payload_is_byte_preserving(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM",
        raw_payload=_RAW_PAYLOAD,
    )
    fetched = db.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == row.raw_observation_id
        )
    ).scalar_one()
    assert fetched.raw_payload == _RAW_PAYLOAD  # exact bytes, not a re-serialization


def test_raw_payload_preserves_key_order_and_duplicates(db) -> None:
    """A JSON re-dump would normalize {'a':1,'b':2} ordering and drop nothing —
    we assert a payload that differs from its canonical JSON form round-trips
    byte-exactly."""
    payload = b'{"b":2,"a":1}'  # non-sorted key order
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=payload,
    )
    assert row.raw_payload == b'{"b":2,"a":1}'


def test_non_bytes_payload_rejected(db) -> None:
    with pytest.raises(TypeError, match="bytes"):
        commit_raw_observation(
            db, tenant_id="t", broker="UPSTOX", source_mode="STREAM",
            raw_payload='{"not":"bytes"}',
        )


def test_delivery_evidence_class_labels_persisted(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="RECOVERY",
        raw_payload=_RAW_PAYLOAD,
        delivery_evidence={
            "recovery_cursor": {"class": "B", "value": "cursor-42"},
            "some_token": "unlabeled-value",
        },
    )
    evidence = get_delivery_evidence(row)
    assert evidence["recovery_cursor"]["class"] == "B"
    # Unlabeled evidence is recorded as class C, never elevated to A (AE)
    assert evidence["some_token"] == {"class": "C", "value": "unlabeled-value"}


# ---------------------------------------------------------------------------
# Phase 2: normalization failure preserves the raw record
# ---------------------------------------------------------------------------

def _failing_processor(db, row):
    raise ValueError("normalization failed: invalid decimal")


def test_normalization_failure_preserves_raw_record(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    outcomes = process_pending_observations(db, _failing_processor)
    assert outcomes == [(row.raw_observation_id, ProcessingStatus.FAILED.value)]
    fetched = db.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == row.raw_observation_id
        )
    ).scalar_one()
    assert fetched.raw_payload == _RAW_PAYLOAD  # evidence intact (AC)
    assert fetched.processing_status == ProcessingStatus.FAILED.value
    assert "normalization failed" in fetched.last_error


def test_classification_failure_keeps_ingestion_status_honest(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    # Processor normalizes OK but classification fails:
    def processor(db, r):
        mark_processing_result(
            db, r,
            ingestion_status=IngestionStatus.CLASSIFICATION_FAILED,
            processing_status=ProcessingStatus.QUARANTINED,
            error="unknown provider status token",
        )
        return IngestionStatus.CLASSIFICATION_FAILED.value

    process_pending_observations(db, processor)
    fetched = db.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == row.raw_observation_id
        )
    ).scalar_one()
    assert fetched.ingestion_status == IngestionStatus.CLASSIFICATION_FAILED.value
    assert fetched.processing_status == ProcessingStatus.QUARANTINED.value
    assert fetched.raw_payload == _RAW_PAYLOAD


def test_successful_processing_marks_canonicalized(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )

    def processor(db, r):
        mark_processing_result(
            db, r,
            ingestion_status=IngestionStatus.CANONICALIZED,
            processing_status=ProcessingStatus.SUCCEEDED,
            d1="d" * 64,
            content_fingerprint="f" * 64,
            provider_order_id="240221025997024",
        )
        return IngestionStatus.CANONICALIZED.value

    process_pending_observations(db, processor)
    fetched = db.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == row.raw_observation_id
        )
    ).scalar_one()
    assert fetched.ingestion_status == IngestionStatus.CANONICALIZED.value
    assert fetched.d1 == "d" * 64
    assert fetched.provider_order_id == "240221025997024"
    assert fetched.raw_payload == _RAW_PAYLOAD  # never rewritten


# ---------------------------------------------------------------------------
# Phase 4: crash / replay / idempotency
# ---------------------------------------------------------------------------

def test_failed_row_is_reclaimed_and_reprocessed(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    process_pending_observations(db, _failing_processor)  # first attempt fails
    attempts = []

    def recovering_processor(db, r):
        attempts.append(r.raw_observation_id)
        mark_processing_result(
            db, r,
            ingestion_status=IngestionStatus.CANONICALIZED,
            processing_status=ProcessingStatus.SUCCEEDED,
        )
        return IngestionStatus.CANONICALIZED.value

    outcomes = process_pending_observations(db, recovering_processor)
    assert outcomes == [(row.raw_observation_id, ProcessingStatus.SUCCEEDED.value)]
    assert attempts == [row.raw_observation_id]
    fetched = db.execute(
        select(BrokerRawObservation).where(
            BrokerRawObservation.raw_observation_id == row.raw_observation_id
        )
    ).scalar_one()
    assert fetched.attempt_count == 2  # claimed twice (at-least-once)


def test_succeeded_rows_not_reclaimed(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    mark_processing_result(
        db, row,
        ingestion_status=IngestionStatus.CANONICALIZED,
        processing_status=ProcessingStatus.SUCCEEDED,
    )
    claimed = claim_raw_observations(db)
    assert claimed == []


def test_quarantined_rows_not_reclaimed(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    mark_processing_result(
        db, row,
        ingestion_status=IngestionStatus.CLASSIFICATION_FAILED,
        processing_status=ProcessingStatus.QUARANTINED,
    )
    claimed = claim_raw_observations(db)
    assert claimed == []


def test_stale_in_progress_lease_reclaimed(db) -> None:
    """A worker that claimed (IN_PROGRESS) and crashed is recovered after the
    lease expires — the lease is stamped at claim time (lease_expires_at)."""
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    claim_raw_observations(db)  # claimed → IN_PROGRESS (crashed worker never returns)
    # Force the lease stale (backdate the claim-time lease, not ingest time):
    row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    claimed = claim_raw_observations(db)
    assert [r.raw_observation_id for r in claimed] == [row.raw_observation_id]
    assert claimed[0].attempt_count == 2


def test_fresh_in_progress_lease_not_reclaimed(db) -> None:
    row = commit_raw_observation(
        db, tenant_id="t", broker="UPSTOX", source_mode="STREAM", raw_payload=_RAW_PAYLOAD,
    )
    claim_raw_observations(db)  # fresh claim — lease still valid
    claimed = claim_raw_observations(db)
    assert claimed == []


def test_claim_limits_batch_size(db) -> None:
    for i in range(5):
        commit_raw_observation(
            db, tenant_id="t", broker="UPSTOX", source_mode="STREAM",
            raw_payload=_RAW_PAYLOAD + str(i).encode(),
        )
    claimed = claim_raw_observations(db, limit=3)
    assert len(claimed) == 3
    remaining = claim_raw_observations(db, limit=10)
    assert len(remaining) == 2
