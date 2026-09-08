"""Day 39 Task 2 — RED test stub.

This test verifies that the durable ingestion pipeline is wired correctly.
It should fail against the pre-remediation implementation because the
required durable behavior was absent.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync import ingest_canonical_event, make_broker_sync_event, BrokerEventType


def test_ingest_canonical_event_is_callable():
    """The ingestion function must be importable and callable."""
    assert callable(ingest_canonical_event)


def test_durable_pipeline_creates_idempotency_record():
    """The pipeline must persist a durable idempotency record.

    This test fails against the pre-remediation implementation because
    it only used in-memory state.
    """
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.broker_sync.models import Base
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    db = Session()

    event = make_broker_sync_event(
        tenant_id="tenant-A",
        broker="upstox",
        event_type=BrokerEventType.ORDER_ACCEPTED,
        broker_order_id="ORD-1",
        canonical_sequence=1,
    )
    result = ingest_canonical_event(event, db, tenant_id="tenant-A")
    assert result["action"] == "APPLIED"

    # Verify durable idempotency record exists
    from app.broker_sync.models import BrokerSyncIdempotency
    from sqlalchemy import select
    idem = db.execute(
        select(BrokerSyncIdempotency).where(
            BrokerSyncIdempotency.canonical_id == event.canonical_id
        )
    ).scalar_one_or_none()
    assert idem is not None, "durable idempotency record must be persisted"
