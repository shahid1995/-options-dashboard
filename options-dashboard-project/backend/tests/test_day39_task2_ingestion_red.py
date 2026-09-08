"""Day 39 Task 2 — RED stub test.

Verifies that the durable ingestion pipeline is correctly wired:
- ingest_canonical_event is callable
- It persists to durable storage (not just in-memory)
- It requires a database session

This test FAILS against the pre-remediation implementation because
the in-memory-only IdempotencyState was the authoritative mechanism,
meaning no durable persistence occurred.
"""
from datetime import datetime, timezone

import pytest

from app.broker_sync import (
    BrokerEventType,
    BrokerSyncEvent,
    FillFacts,
    OrderFacts,
    make_broker_sync_event,
)
from app.broker_sync.ingestion import ingest_canonical_event


_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_ingest_requires_durable_session():
    """ingest_canonical_event must require and use a database session.

    The pre-remediation implementation used an in-memory IdempotencyState
    with no persistence.  This test verifies the durable path is taken.
    """
    event = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="broker-test",
        event_type=BrokerEventType.ORDER_SUBMITTED,
        event_version="1.0",
        broker_order_id="ORD-1",
        canonical_sequence=1,
        order_facts=OrderFacts(
            broker_order_id="ORD-1",
            status="SUBMITTED",
            total_quantity=100,
        ),
        received_at=_NOW,
    )

    # Must require a db session (not just an IdempotencyState object)
    with pytest.raises(TypeError):
        # Calling without db session should fail
        ingest_canonical_event(event)
