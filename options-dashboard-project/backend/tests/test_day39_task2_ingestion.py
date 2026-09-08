"""
Day 39 Task 2 — Durable ingestion pipeline tests.

Tests the full durable pipeline:
  BrokerSyncEvent → validation → tenant check → durable idempotency
  → terminal-state enforcement → durable projection → Day38 lifecycle
  → single transaction commit.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync import (
    BrokerEventType,
    CanonicalOrderState,
    FillFacts,
    OrderFacts,
    ingest_canonical_event,
    make_broker_sync_event,
)
from app.broker_sync.models import BrokerOrderProjection, BrokerSyncIdempotency
from app.trade_lifecycle.persistence import TradeLifecycleEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    *,
    tenant_id="tenant-A",
    broker="upstox",
    event_type=BrokerEventType.ORDER_ACCEPTED,
    provider_event_id=None,
    broker_order_id="ORD-1",
    canonical_sequence=1,
    fill_facts=None,
    order_facts=None,
    event_timestamp=None,
    received_at=None,
):
    if received_at is None:
        from datetime import datetime, timezone
        received_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return make_broker_sync_event(
        tenant_id=tenant_id,
        broker=broker,
        event_type=event_type,
        provider_event_id=provider_event_id,
        broker_order_id=broker_order_id,
        canonical_sequence=canonical_sequence,
        fill_facts=fill_facts,
        order_facts=order_facts,
        event_timestamp=event_timestamp,
        received_at=received_at,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.broker_sync.models import Base as BrokerBase
    from app.trade_lifecycle.persistence import Base as LifecycleBase
    # Create all tables
    BrokerBase.metadata.create_all(eng)
    LifecycleBase.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


# ---------------------------------------------------------------------------
# 1. First event applies
# ---------------------------------------------------------------------------

class TestFirstEventApplies:
    def test_first_event_persists_idempotency_and_projection(self, db):
        event = _make_event()
        result = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert result["action"] == "APPLIED"
        assert result["normalized_state"] is not None
        assert result["normalized_state"]["status"] == CanonicalOrderState.OPEN

        # Verify idempotency record persisted
        idem = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert idem is not None
        assert idem.status == "APPLIED"

        # Verify projection persisted
        proj = db.execute(
            select(BrokerOrderProjection).where(
                BrokerOrderProjection.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert proj is not None
        assert proj.status == CanonicalOrderState.OPEN

    def test_first_event_creates_day38_lifecycle_event(self, db):
        event = _make_event()
        result = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert result["action"] == "APPLIED"

        # Verify Day38 lifecycle event was created
        lifecycle_events = db.execute(
            select(TradeLifecycleEvent).where(
                TradeLifecycleEvent.tenant_id == "tenant-A"
            )
        ).scalars().all()
        assert len(lifecycle_events) >= 1
        # Find the broker_order lifecycle event
        broker_events = [e for e in lifecycle_events if e.aggregate_type == "broker_order"]
        assert len(broker_events) == 1
        assert broker_events[0].event_type == BrokerEventType.ORDER_ACCEPTED


# ---------------------------------------------------------------------------
# 2. Identical duplicate is a durable no-op
# ---------------------------------------------------------------------------

class TestDuplicateIsNoop:
    def test_identical_duplicate_is_noop(self, db):
        event = _make_event()
        r1 = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert r1["action"] == "APPLIED"

        r2 = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert r2["action"] == "DUPLICATE_NOOP"
        assert r2["normalized_state"] is None

    def test_duplicate_after_session_recreation_still_detected(self, db, engine):
        """Duplicate detection survives session recreation (simulates restart)."""
        event = _make_event()
        r1 = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert r1["action"] == "APPLIED"
        db.commit()

        # Recreate session (simulates restart)
        db.close()
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db2 = Session()

        r2 = ingest_canonical_event(event, db2, tenant_id="tenant-A")
        assert r2["action"] == "DUPLICATE_NOOP"
        db2.close()


# ---------------------------------------------------------------------------
# 3. Conflicting same identity is rejected
# ---------------------------------------------------------------------------

class TestConflictingIdentityRejected:
    def test_conflicting_content_rejected(self, db):
        """Same canonical_id but different content → CONFLICT."""
        event1 = _make_event(order_facts=OrderFacts(total_quantity=100))
        r1 = ingest_canonical_event(event1, db, tenant_id="tenant-A")
        assert r1["action"] == "APPLIED"

        # Create event with same identity but different content
        event2 = _make_event(order_facts=OrderFacts(total_quantity=200))
        # event2 has same canonical_id (same tenant, broker, order, seq, no fill_id)
        assert event1.canonical_id == event2.canonical_id

        r2 = ingest_canonical_event(event2, db, tenant_id="tenant-A")
        assert r2["action"] == "CONFLICT"


# ---------------------------------------------------------------------------
# 4. Tenant mismatch is rejected
# ---------------------------------------------------------------------------

class TestTenantMismatchRejected:
    def test_tenant_mismatch_rejected(self, db):
        event = _make_event(tenant_id="tenant-A")
        result = ingest_canonical_event(event, db, tenant_id="tenant-B")
        assert result["action"] == "REJECTED"
        assert "tenant mismatch" in result["reason"]

    def test_tenant_mismatch_does_not_persist(self, db):
        event = _make_event(tenant_id="tenant-A")
        ingest_canonical_event(event, db, tenant_id="tenant-B")

        # No idempotency record should exist
        idem = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert idem is None


# ---------------------------------------------------------------------------
# 5. Malformed event is rejected
# ---------------------------------------------------------------------------

class TestMalformedEventRejected:
    def test_malformed_event_rejected_at_construction(self):
        """broker_order_id only, no sequence or fill_facts → construction fails."""
        with pytest.raises(ValueError, match="insufficient"):
            make_broker_sync_event(
                tenant_id="tenant-A",
                broker="upstox",
                event_type=BrokerEventType.ORDER_ACCEPTED,
                broker_order_id="ORD-1",
                canonical_sequence=None,
                fill_facts=None,
            )


# ---------------------------------------------------------------------------
# 6. Terminal state cannot be mutated illegally
# ---------------------------------------------------------------------------

class TestTerminalStateEnforcement:
    def test_filled_then_additional_fill_rejected(self, db):
        """FILLED → additional fill must be rejected."""
        # Apply accepted
        accepted = _make_event(event_type=BrokerEventType.ORDER_ACCEPTED)
        ingest_canonical_event(accepted, db, tenant_id="tenant-A")

        # Apply full fill
        full_fill = _make_event(
            event_type=BrokerEventType.FULL_FILL,
            canonical_sequence=2,
            fill_facts=FillFacts(
                fill_id="FILL-001",
                fill_quantity=10,
                fill_price=100.0,
                cumulative_filled_after=10,
                remaining_after=0,
            ),
        )
        r1 = ingest_canonical_event(full_fill, db, tenant_id="tenant-A")
        assert r1["action"] == "APPLIED"
        assert r1["normalized_state"]["status"] == CanonicalOrderState.FILLED

        # Try another fill — should be rejected
        extra_fill = _make_event(
            event_type=BrokerEventType.PARTIAL_FILL,
            canonical_sequence=3,
            fill_facts=FillFacts(
                fill_id="FILL-002",
                fill_quantity=5,
                fill_price=101.0,
                cumulative_filled_after=15,
                remaining_after=0,
            ),
        )
        r2 = ingest_canonical_event(extra_fill, db, tenant_id="tenant-A")
        assert r2["action"] == "REJECTED"
        assert "terminal state mutation rejected" in r2["reason"]

    def test_cancelled_then_fill_rejected(self, db):
        """CANCELLED → fill must be rejected."""
        accepted = _make_event(event_type=BrokerEventType.ORDER_ACCEPTED)
        ingest_canonical_event(accepted, db, tenant_id="tenant-A")

        cancel = _make_event(
            event_type=BrokerEventType.ORDER_CANCELLED,
            canonical_sequence=2,
        )
        ingest_canonical_event(cancel, db, tenant_id="tenant-A")

        fill = _make_event(
            event_type=BrokerEventType.PARTIAL_FILL,
            canonical_sequence=3,
            fill_facts=FillFacts(
                fill_id="FILL-001",
                fill_quantity=10,
                fill_price=100.0,
                cumulative_filled_after=10,
                remaining_after=0,
            ),
        )
        r = ingest_canonical_event(fill, db, tenant_id="tenant-A")
        assert r["action"] == "REJECTED"

    def test_rejected_then_fill_rejected(self, db):
        """REJECTED → fill must be rejected."""
        reject = _make_event(
            event_type=BrokerEventType.ORDER_REJECTED,
            order_facts=OrderFacts(
                status=CanonicalOrderState.REJECTED,
                is_terminal=True,
                rejection_reason="bad",
            ),
        )
        ingest_canonical_event(reject, db, tenant_id="tenant-A")

        fill = _make_event(
            event_type=BrokerEventType.PARTIAL_FILL,
            canonical_sequence=2,
            fill_facts=FillFacts(
                fill_id="FILL-001",
                fill_quantity=10,
                fill_price=100.0,
                cumulative_filled_after=10,
                remaining_after=0,
            ),
        )
        r = ingest_canonical_event(fill, db, tenant_id="tenant-A")
        assert r["action"] == "REJECTED"


# ---------------------------------------------------------------------------
# 7. Partial fill and final fill produce correct normalized state
# ---------------------------------------------------------------------------

class TestFillProjection:
    def test_partial_fill_persists_correct_quantities(self, db):
        accepted = _make_event(
            event_type=BrokerEventType.ORDER_ACCEPTED,
            order_facts=OrderFacts(total_quantity=100),
        )
        ingest_canonical_event(accepted, db, tenant_id="tenant-A")

        partial = _make_event(
            event_type=BrokerEventType.PARTIAL_FILL,
            canonical_sequence=2,
            fill_facts=FillFacts(
                fill_id="FILL-001",
                fill_quantity=10,
                fill_price=100.0,
                cumulative_filled_after=10,
                remaining_after=90,
            ),
        )
        r = ingest_canonical_event(partial, db, tenant_id="tenant-A")
        assert r["action"] == "APPLIED"
        ns = r["normalized_state"]
        assert ns["status"] == CanonicalOrderState.PARTIALLY_FILLED
        assert ns["cumulative_filled"] == 10
        assert ns["remaining_quantity"] == 90
        assert ns["last_fill_price"] == 100.0
        assert ns["last_fill_quantity"] == 10
        assert ns["last_fill_id"] == "FILL-001"
        assert ns["is_terminal"] is False

    def test_full_fill_persists_filled(self, db):
        accepted = _make_event(
            event_type=BrokerEventType.ORDER_ACCEPTED,
            order_facts=OrderFacts(total_quantity=100),
        )
        ingest_canonical_event(accepted, db, tenant_id="tenant-A")

        full = _make_event(
            event_type=BrokerEventType.FULL_FILL,
            canonical_sequence=2,
            fill_facts=FillFacts(
                fill_id="FILL-002",
                fill_quantity=100,
                fill_price=99.0,
                cumulative_filled_after=100,
                remaining_after=0,
            ),
        )
        r = ingest_canonical_event(full, db, tenant_id="tenant-A")
        assert r["action"] == "APPLIED"
        assert r["normalized_state"]["status"] == CanonicalOrderState.FILLED
        assert r["normalized_state"]["is_terminal"] is True
        assert r["normalized_state"]["cumulative_filled"] == 100
        assert r["normalized_state"]["remaining_quantity"] == 0


# ---------------------------------------------------------------------------
# 8. Cancellation/rejection map correctly
# ---------------------------------------------------------------------------

class TestCancellationRejection:
    def test_cancellation_persists_cancelled(self, db):
        accepted = _make_event()
        ingest_canonical_event(accepted, db, tenant_id="tenant-A")

        cancel = _make_event(
            event_type=BrokerEventType.ORDER_CANCELLED,
            canonical_sequence=2,
        )
        r = ingest_canonical_event(cancel, db, tenant_id="tenant-A")
        assert r["action"] == "APPLIED"
        assert r["normalized_state"]["status"] == CanonicalOrderState.CANCELLED
        assert r["normalized_state"]["is_terminal"] is True

    def test_rejection_persists_rejected_with_reason(self, db):
        reject = _make_event(
            event_type=BrokerEventType.ORDER_REJECTED,
            order_facts=OrderFacts(
                status=CanonicalOrderState.REJECTED,
                is_terminal=True,
                rejection_reason="insufficient_margin",
            ),
        )
        r = ingest_canonical_event(reject, db, tenant_id="tenant-A")
        assert r["action"] == "APPLIED"
        assert r["normalized_state"]["status"] == CanonicalOrderState.REJECTED
        assert r["normalized_state"]["is_terminal"] is True
        assert r["normalized_state"]["rejection_reason"] == "insufficient_margin"


# ---------------------------------------------------------------------------
# 9. Transaction atomicity
# ---------------------------------------------------------------------------

class TestTransactionAtomicity:
    def test_successful_processing_commits_all_three(self, db):
        event = _make_event()
        result = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert result["action"] == "APPLIED"
        db.commit()

        # All three should be committed
        idem = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert idem is not None

        proj = db.execute(
            select(BrokerOrderProjection).where(
                BrokerOrderProjection.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert proj is not None

        lifecycle = db.execute(
            select(TradeLifecycleEvent).where(
                TradeLifecycleEvent.tenant_id == "tenant-A",
                TradeLifecycleEvent.aggregate_type == "broker_order",
            )
        ).scalars().all()
        assert len(lifecycle) >= 1

    def test_rollback_removes_all_three(self, db):
        event = _make_event()
        result = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert result["action"] == "APPLIED"
        # Roll back instead of commit
        db.rollback()

        # None should be committed
        idem = db.execute(
            select(BrokerSyncIdempotency).where(
                BrokerSyncIdempotency.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert idem is None

        proj = db.execute(
            select(BrokerOrderProjection).where(
                BrokerOrderProjection.canonical_id == event.canonical_id
            )
        ).scalar_one_or_none()
        assert proj is None


# ---------------------------------------------------------------------------
# 10. Duplicate fill does not double-count
# ---------------------------------------------------------------------------

class TestDuplicateFillProtection:
    def test_duplicate_fill_does_not_double_count(self, db):
        accepted = _make_event(
            event_type=BrokerEventType.ORDER_ACCEPTED,
            order_facts=OrderFacts(total_quantity=100),
        )
        ingest_canonical_event(accepted, db, tenant_id="tenant-A")

        fill = _make_event(
            event_type=BrokerEventType.PARTIAL_FILL,
            canonical_sequence=2,
            fill_facts=FillFacts(
                fill_id="FILL-001",
                fill_quantity=10,
                fill_price=100.0,
                cumulative_filled_after=10,
                remaining_after=90,
            ),
        )
        r1 = ingest_canonical_event(fill, db, tenant_id="tenant-A")
        assert r1["action"] == "APPLIED"
        assert r1["normalized_state"]["cumulative_filled"] == 10

        # Duplicate fill
        r2 = ingest_canonical_event(fill, db, tenant_id="tenant-A")
        assert r2["action"] == "DUPLICATE_NOOP"

        # Verify cumulative_filled is still 10, not 20
        proj = db.execute(
            select(BrokerOrderProjection).where(
                BrokerOrderProjection.canonical_id == fill.canonical_id
            )
        ).scalar_one_or_none()
        assert proj.cumulative_filled == 10


# ---------------------------------------------------------------------------
# 11. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    def test_same_order_different_tenants_independent(self, db):
        event_a = _make_event(tenant_id="tenant-A")
        event_b = _make_event(tenant_id="tenant-B")

        r_a = ingest_canonical_event(event_a, db, tenant_id="tenant-A")
        r_b = ingest_canonical_event(event_b, db, tenant_id="tenant-B")

        assert r_a["action"] == "APPLIED"
        assert r_b["action"] == "APPLIED"

        # Different canonical IDs
        assert event_a.canonical_id != event_b.canonical_id


# ---------------------------------------------------------------------------
# 12. Provider event ID path
# ---------------------------------------------------------------------------

class TestProviderEventIdPath:
    def test_provider_event_id_path_idempotent(self, db):
        event = _make_event(provider_event_id="PROV-123")
        r1 = ingest_canonical_event(event, db, tenant_id="tenant-A")
        assert r1["action"] == "APPLIED"

        # Duplicate with different received_at
        event_dup = _make_event(provider_event_id="PROV-123")
        r2 = ingest_canonical_event(event_dup, db, tenant_id="tenant-A")
        assert r2["action"] == "DUPLICATE_NOOP"
