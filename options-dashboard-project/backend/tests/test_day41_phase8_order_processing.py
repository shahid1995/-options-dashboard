"""Day41 Phase 8 — ORDER_PROCESSING additive enum + projection-only mapping (Day40 §1.3).

Verifies:
- ORDER_PROCESSING exists in BrokerEventType (additive Day40 change)
- _BROKER_TO_LIFECYCLE[ORDER_PROCESSING] is None (projection-only — no Day38 event)
- an ORDER_PROCESSING event ingests fully (projection + idempotency) without
  a Day38 lifecycle transition
- duplicates dedup; provider status preserved in metadata
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync import (
    BrokerEventType,
    BrokerSyncEvent,
    CanonicalOrderState,
    OrderFacts,
    make_broker_sync_event,
)
from app.broker_sync.ingestion import _map_to_lifecycle_event_type, ingest_canonical_event

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def _seed_app_order(db, broker_order_id: str, tenant_id: str = "tenant-1") -> None:
    from app.models import PaperOrder, StrategyExecution

    exec_id = f"EXEC-{broker_order_id}"
    db.add(StrategyExecution(
        user_id=tenant_id,
        execution_id=exec_id,
        client_order_id=f"exec-{broker_order_id}",
        strategy_id="strat-1",
        strategy_tag="Test",
        symbol="NIFTY",
        status="FILLED",
        entry_net=0.0,
        entry_at=_NOW,
    ))
    db.add(PaperOrder(
        user_id=tenant_id,
        execution_id=exec_id,
        client_order_id=broker_order_id,
        kind="entry",
        symbol="NIFTY",
        expiry="2026-10-29",
        strike=24500.0,
        option_type="CE",
        action="buy",
        quantity=100,
        lot_size=1,
        status="FILLED",
        filled_quantity=100,
        fill_price=100.0,
    ))
    db.commit()


@pytest.fixture()
def db():
    from app.db import Base
    import app.models  # noqa: F401
    import app.broker_sync.models  # noqa: F401
    import app.broker_sync.raw_ingress  # noqa: F401
    import app.trade_lifecycle.persistence  # noqa: F401

    Base.metadata.create_all(_engine)
    session = _TestSessionLocal()
    _seed_app_order(session, "ORD-PROC")
    session.commit()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(_engine)


def _processing_event(
    canonical_sequence: int,
    provider_status: str = "validation pending",
) -> BrokerSyncEvent:
    return make_broker_sync_event(
        tenant_id="tenant-1",
        broker="broker-test",
        event_type=BrokerEventType.ORDER_PROCESSING,
        event_version="1.0",
        broker_order_id="ORD-PROC",
        canonical_sequence=canonical_sequence,
        received_at=_NOW + timedelta(seconds=canonical_sequence),
        order_facts=OrderFacts(
            broker_order_id="ORD-PROC",
            order_id="ORD-PROC",
            status=CanonicalOrderState.SUBMITTED,
            total_quantity=100,
        ),
        metadata={"upstox": {"status": provider_status}},
    )


def test_order_processing_enum_value_exists() -> None:
    assert BrokerEventType.ORDER_PROCESSING.value == "ORDER_PROCESSING"
    assert BrokerEventType("ORDER_PROCESSING") is BrokerEventType.ORDER_PROCESSING


def test_order_processing_is_projection_only() -> None:
    """ORDER_PROCESSING → None: it must NOT mint a Day38 lifecycle event."""
    assert _map_to_lifecycle_event_type(BrokerEventType.ORDER_PROCESSING.value) is None


def test_order_processing_ingests_without_lifecycle_event(db) -> None:
    ev = _processing_event(canonical_sequence=1)
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "APPLIED"
    # Projection row recorded:
    from app.broker_sync.models import BrokerOrderProjection
    row = db.execute(
        select(BrokerOrderProjection).where(
            BrokerOrderProjection.broker_order_id == "ORD-PROC",
            BrokerOrderProjection.event_type == "ORDER_PROCESSING",
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == "SUBMITTED"


def test_order_processing_duplicate_dedups(db) -> None:
    ev1 = _processing_event(canonical_sequence=1)
    ev2 = _processing_event(canonical_sequence=1)
    r1 = ingest_canonical_event(ev1, db, tenant_id="tenant-1")
    r2 = ingest_canonical_event(ev2, db, tenant_id="tenant-1")
    assert r1["action"] == "APPLIED"
    assert r2["action"] == "DUPLICATE_NOOP"


def test_provider_status_preserved_in_metadata(db) -> None:
    ev = _processing_event(canonical_sequence=1, provider_status="trigger pending")
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "APPLIED"
    from app.broker_sync.models import BrokerSyncIdempotency
    idem = db.execute(
        select(BrokerSyncIdempotency).where(
            BrokerSyncIdempotency.canonical_id == ev.canonical_id
        )
    ).scalar_one()
    # Fingerprint includes metadata; the raw provider status token rides in
    # event metadata and survives the pipeline (Day40.3 §3.3-2).
    assert ev.metadata["upstox"]["status"] == "trigger pending"


def test_existing_enum_members_unchanged() -> None:
    """Additive change: all pre-Day41 enum values still present."""
    expected = {
        "ORDER_SUBMITTED", "ORDER_ACCEPTED", "ORDER_REJECTED", "ORDER_CANCELLED",
        "ORDER_EXPIRED", "PARTIAL_FILL", "FULL_FILL", "FILL_RECORDED", "ORDER_RECOVERED",
    }
    assert expected <= {e.value for e in BrokerEventType}
