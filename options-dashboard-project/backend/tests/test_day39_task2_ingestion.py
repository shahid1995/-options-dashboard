"""Day 39 Task 2 — Durable ingestion pipeline tests.

Tests the full durable pipeline:
  BrokerSyncEvent → validation → tenant check → broker ordering
    → durable idempotency → terminal-state enforcement → projection
    → Day38 lifecycle mapping → single transaction

Behavioral tests — not implementation-coupled.  All idempotency and
projection assertions hit durable SQL state.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import sessionmaker

from app.broker_sync import (
    BrokerEventType,
    BrokerEventSourceMode,
    BrokerSyncEvent,
    CanonicalOrderState,
    FillFacts,
    OrderFacts,
    make_broker_sync_event,
)
from app.broker_sync.ingestion import IngestionError, ingest_canonical_event
from app.broker_sync.models import BrokerOrderProjection, BrokerSyncIdempotency, BrokerSyncSequenceAnchor

# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

from sqlalchemy.pool import StaticPool

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


@pytest.fixture()
def db():
    """Provide a clean SQLite database session for each test (deterministic)."""
    from app.db import Base
    Base.metadata.create_all(_engine)
    session = _TestSessionLocal()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(_engine)


_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def _make_submitted_event(
    broker_order_id: str = "ORD-1",
    tenant_id: str = "tenant-1",
    broker: str = "broker-test",
    canonical_sequence: int | None = 1,
    event_type: str = BrokerEventType.ORDER_SUBMITTED.value,
    total_quantity: int | None = 100,
    received_at: datetime | None = None,
    event_timestamp: datetime | None = None,
) -> BrokerSyncEvent:
    return make_broker_sync_event(
        tenant_id=tenant_id,
        broker=broker,
        event_type=event_type,
        event_version="1.0",
        broker_order_id=broker_order_id,
        canonical_sequence=canonical_sequence,
        received_at=received_at or (_NOW + timedelta(seconds=1)),
        event_timestamp=event_timestamp,
        order_facts=OrderFacts(
            broker_order_id=broker_order_id,
            status=CanonicalOrderState.SUBMITTED,
            total_quantity=total_quantity,
            cumulative_filled=0,
        ),
    )


def _make_accepted_event(
    broker_order_id: str = "ORD-1",
    canonical_sequence: int = 2,
    received_at: datetime | None = None,
) -> BrokerSyncEvent:
    return make_broker_sync_event(
        tenant_id="tenant-1",
        broker="broker-test",
        event_type=BrokerEventType.ORDER_ACCEPTED,
        event_version="1.0",
        broker_order_id=broker_order_id,
        canonical_sequence=canonical_sequence,
        received_at=received_at or (_NOW + timedelta(seconds=2)),
        order_facts=OrderFacts(
            broker_order_id=broker_order_id,
            status=CanonicalOrderState.OPEN,
            total_quantity=100,
        ),
    )


def _make_full_fill_event(
    broker_order_id: str = "ORD-1",
    canonical_sequence: int | None = 2,
    cumulative_filled_after: int = 100,
    total_quantity: int = 100,
    received_at: datetime | None = None,
) -> BrokerSyncEvent:
    return make_broker_sync_event(
        tenant_id="tenant-1",
        broker="broker-test",
        event_type=BrokerEventType.FULL_FILL.value,
        event_version="1.0",
        broker_order_id=broker_order_id,
        canonical_sequence=canonical_sequence,
        order_facts=OrderFacts(
            broker_order_id=broker_order_id,
            status=CanonicalOrderState.FILLED,
            total_quantity=total_quantity,
            cumulative_filled=cumulative_filled_after,
            is_terminal=True,
        ),
        fill_facts=FillFacts(
            fill_quantity=cumulative_filled_after,
            fill_price=100.0,
            cumulative_filled_after=cumulative_filled_after,
            remaining_after=total_quantity - cumulative_filled_after,
        ),
        received_at=received_at or (_NOW + timedelta(seconds=2)),
    )


# ---------------------------------------------------------------------------
# 1. Idempotency tests
# ---------------------------------------------------------------------------

class TestIdempotency:

    def test_first_event_persists_and_applies(self, db):
        """First event persists and applies."""
        event = _make_submitted_event()
        result = ingest_canonical_event(event, db)
        assert result["action"] == "APPLIED"
        assert result["normalized_state"]["status"] == "SUBMITTED"

        # Idempotency record is durably persisted
        row = db.execute(
            text("SELECT canonical_id, content_fingerprint, status FROM broker_sync_idempotency")
        ).fetchone()
        assert row is not None
        assert row.canonical_id == event.canonical_id
        assert row.status == "APPLIED"

    def test_identical_duplicate_is_durable_noop(self, db):
        """Identical duplicate is a durable no-op (survives session recreation)."""
        event = _make_submitted_event()
        ingest_canonical_event(event, db)
        db.commit()

        # Simulate process/session restart — close and reopen session
        from app.db import Base
        Base.metadata.create_all(_engine)
        new_db = _TestSessionLocal()

        result = ingest_canonical_event(event, new_db)
        assert result["action"] == "DUPLICATE_NOOP"
        # No duplicate projection row
        count = new_db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection WHERE canonical_id = :cid"),
            {"cid": event.canonical_id},
        ).scalar()
        assert count == 1
        new_db.close()

    def test_conflicting_same_identity_rejected(self, db):
        """Same canonical_id + different content → CONFLICT."""
        event = _make_submitted_event()
        ingest_canonical_event(event, db)

        # Same canonical_id (seq=1) but different total_quantity
        different_event = BrokerSyncEvent(
            tenant_id="tenant-1",
            broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED,
            event_version="1.0",
            received_at=_NOW + timedelta(seconds=2),
            provider_event_id=None,
            broker_order_id="ORD-1",
            canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id="ORD-1",
                status=CanonicalOrderState.SUBMITTED,
                total_quantity=999,  # different!
            ),
        )
        result = ingest_canonical_event(different_event, db)
        assert result["action"] == "CONFLICT"

    def test_duplicate_after_session_recreation_detected(self, db):
        """Duplicate detected after session recreation (durable)."""
        event = _make_submitted_event()
        ingest_canonical_event(event, db)
        db.commit()

        # Recreate session
        from app.db import Base
        Base.metadata.create_all(_engine)
        new_db = _TestSessionLocal()
        result = ingest_canonical_event(event, new_db)
        assert result["action"] == "DUPLICATE_NOOP"
        new_db.close()

    def test_cross_tenant_identity_rejected(self, db):
        """Cross-tenant identity (different tenant) rejected."""
        event = _make_submitted_event(tenant_id="tenant-1")
        result = ingest_canonical_event(event, db, tenant_id="tenant-2")
        assert result["action"] == "REJECTED"
        assert "tenant mismatch" in result["reason"]


# ---------------------------------------------------------------------------
# 2. Projection tests
# ---------------------------------------------------------------------------

class TestProjection:

    def test_accepted_event_persists_normalized_state(self, db):
        """ORDER_ACCEPTED persists normalized state OPEN."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        accepted = _make_accepted_event(canonical_sequence=2)
        result = ingest_canonical_event(accepted, db)
        assert result["action"] == "APPLIED"
        assert result["normalized_state"]["status"] == "OPEN"
        assert result["normalized_state"]["total_quantity"] == 100

    def test_submitted_event_persists(self, db):
        event = _make_submitted_event()
        result = ingest_canonical_event(event, db)
        assert result["action"] == "APPLIED"
        assert result["normalized_state"]["status"] == "SUBMITTED"

    def test_partial_fill_persists_correct_quantities(self, db):
        """PARTIAL_FILL persists correct cumulative/remaining."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(
                fill_quantity=50, fill_price=100.0,
                cumulative_filled_after=50, remaining_after=50,
            ),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "APPLIED"
        ns = result["normalized_state"]
        assert ns["status"] == "PARTIALLY_FILLED"
        assert ns["cumulative_filled"] == 50
        assert ns["remaining_quantity"] == 50
        assert ns["last_fill_quantity"] == 50
        assert ns["last_fill_price"] == 100.0
        assert ns["fill_count"] == 1

    def test_final_fill_persists_filled(self, db):
        """FULL_FILL persists FILLED (terminal)."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        fill = _make_full_fill_event(canonical_sequence=2)
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "APPLIED"
        ns = result["normalized_state"]
        assert ns["status"] == "FILLED"
        assert ns["is_terminal"] is True

    def test_cancellation_persists_cancelled(self, db):
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        cancel = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_CANCELLED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.CANCELLED,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(cancel, db)
        assert result["action"] == "APPLIED"
        ns = result["normalized_state"]
        assert ns["status"] == "CANCELLED"
        assert ns["is_terminal"] is True

    def test_rejection_persists_rejected(self, db):
        reject = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_REJECTED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.REJECTED,
                total_quantity=100, rejection_reason="insufficient_margin",
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
        result = ingest_canonical_event(reject, db)
        assert result["action"] == "APPLIED"
        ns = result["normalized_state"]
        assert ns["status"] == "REJECTED"
        assert ns["is_terminal"] is True
        assert ns["rejection_reason"] == "insufficient_margin"

    def test_duplicate_fill_does_not_double_count(self, db):
        """Same canonical fill event applied twice does not double-count."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(
                fill_quantity=50, fill_price=100.0,
                cumulative_filled_after=50, remaining_after=50,
            ),
            received_at=_NOW + timedelta(seconds=2),
        )
        # First application
        result1 = ingest_canonical_event(fill, db)
        assert result1["action"] == "APPLIED"
        # Second application (identical duplicate)
        result2 = ingest_canonical_event(fill, db)
        assert result2["action"] == "DUPLICATE_NOOP"

        # Projection shows only one fill row with cumulative=50
        count = db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection WHERE broker_order_id = 'ORD-1'"),
        ).scalar()
        assert count == 2  # submit + fill
        latest = db.execute(
            text("SELECT cumulative_filled FROM broker_order_projection "
                 "WHERE broker_order_id = 'ORD-1' ORDER BY canonical_sequence DESC NULLS LAST LIMIT 1")
        ).fetchone()
        assert latest[0] == 50


# ---------------------------------------------------------------------------
# 3. Terminal-state enforcement tests
# ---------------------------------------------------------------------------

class TestTerminalStates:

    def test_filled_then_fill_rejected(self, db):
        """FILLED → additional fill is rejected."""
        # 1: submit, 2: fill to 50, 3: fill to 100 (FILLED), 4: additional fill
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        half_fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        ingest_canonical_event(half_fill, db)

        full_fill = _make_full_fill_event(broker_order_id="ORD-1", canonical_sequence=3)
        ingest_canonical_event(full_fill, db)

        # Now FILLED → additional fill (seq=4, different content)
        after_fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=4,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=80,
            ),
            fill_facts=FillFacts(fill_quantity=80, fill_price=100.0,
                                 cumulative_filled_after=80, remaining_after=20),
            received_at=_NOW + timedelta(seconds=4),
        )
        result = ingest_canonical_event(after_fill, db)
        assert result["action"] == "REJECTED"
        assert "terminal" in result["reason"].lower()

    def test_filled_then_cancellation_rejected(self, db):
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        full_fill = _make_full_fill_event(canonical_sequence=2)
        ingest_canonical_event(full_fill, db)

        cancel = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_CANCELLED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.CANCELLED,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=3),
        )
        result = ingest_canonical_event(cancel, db)
        assert result["action"] == "REJECTED"
        assert "terminal" in result["reason"].lower()

    def test_cancelled_then_fill_rejected(self, db):
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        cancel = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_CANCELLED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.CANCELLED,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=2),
        )
        ingest_canonical_event(cancel, db)

        fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=3),
        )
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "REJECTED"
        assert "terminal" in result["reason"].lower()

    def test_rejected_then_fill_rejected(self, db):
        reject = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_REJECTED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.REJECTED,
                total_quantity=100, rejection_reason="test_reject",
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
        ingest_canonical_event(reject, db)

        fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "REJECTED"
        assert "terminal" in result["reason"].lower()

    def test_expired_then_fill_rejected(self, db):
        """EXPIRED → arbitrary mutation rejected."""
        expire = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_EXPIRED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.EXPIRED,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
        ingest_canonical_event(expire, db)

        fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "REJECTED"
        assert "terminal" in result["reason"].lower()

    def test_order_recovered_rejected(self, db):
        """ORDER_RECOVERED must be rejected — not bypass terminal protection."""
        event = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_RECOVERED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.UNKNOWN,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
        result = ingest_canonical_event(event, db)
        assert result["action"] == "REJECTED"
        assert "ORDER_RECOVERED" in result["reason"]


# ---------------------------------------------------------------------------
# 4. Transactionality tests
# ---------------------------------------------------------------------------

class TestTransactionality:

    def test_rollback_on_lifecycle_failure_rolls_back_idempotency(self, db):
        """If Day38 lifecycle persistence fails, idempotency record must roll back."""
        from app.broker_sync import ingestion as ing_mod

        original = ing_mod.append_lifecycle_event

        def failing_append(*args, **kwargs):
            raise RuntimeError("simulated lifecycle failure")

        ing_mod.append_lifecycle_event = failing_append
        try:
            event = _make_submitted_event()
            with pytest.raises(RuntimeError):
                ingest_canonical_event(event, db)
            db.rollback()

            # Idempotency record must NOT exist
            count = db.execute(text("SELECT COUNT(*) FROM broker_sync_idempotency")).scalar()
            assert count == 0
            # Projection must NOT exist
            count = db.execute(text("SELECT COUNT(*) FROM broker_order_projection")).scalar()
            assert count == 0
        finally:
            ing_mod.append_lifecycle_event = original

    def test_rollback_on_projection_failure_rolls_back_idempotency(self, db):
        """If projection fails, idempotency record must roll back."""
        from app.broker_sync import ingestion as ing_mod

        original = ing_mod._build_projection

        def failing_build(*args, **kwargs):
            raise RuntimeError("simulated projection failure")

        ing_mod._build_projection = failing_build
        try:
            event = _make_submitted_event()
            with pytest.raises(RuntimeError):
                ingest_canonical_event(event, db)
            db.rollback()

            count = db.execute(text("SELECT COUNT(*) FROM broker_sync_idempotency")).scalar()
            assert count == 0
        finally:
            ing_mod._build_projection = original

    def test_successful_processing_commits_all_three(self, db):
        """Successful processing commits idempotency + projection + lifecycle."""
        event = _make_submitted_event()
        result = ingest_canonical_event(event, db)
        assert result["action"] == "APPLIED"

        idem_count = db.execute(text("SELECT COUNT(*) FROM broker_sync_idempotency")).scalar()
        proj_count = db.execute(text("SELECT COUNT(*) FROM broker_order_projection")).scalar()
        lifecycle_count = db.execute(
            text("SELECT COUNT(*) FROM trade_lifecycle_events")
        ).scalar()
        assert idem_count == 1
        assert proj_count == 1
        assert lifecycle_count == 1

    def test_retry_after_rollback_can_process(self, db):
        """After a rollback, the event can be successfully re-processed."""
        from app.broker_sync import ingestion as ing_mod

        call_count = [0]
        original = ing_mod.append_lifecycle_event

        def flaky_append(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient lifecycle failure")
            return original(*args, **kwargs)

        ing_mod.append_lifecycle_event = flaky_append
        try:
            event = _make_submitted_event()
            # First attempt fails
            with pytest.raises(RuntimeError):
                ingest_canonical_event(event, db)
            db.rollback()

            # Second attempt succeeds
            result = ingest_canonical_event(event, db)
            assert result["action"] == "APPLIED"
        finally:
            ing_mod.append_lifecycle_event = original


# ---------------------------------------------------------------------------
# 5. Day38 integration tests
# ---------------------------------------------------------------------------

class TestDay38Integration:

    def test_canonical_broker_event_produces_expected_day38_lifecycle_event(self, db):
        """BrokerSyncEvent → Task2 ingestion → Day38 lifecycle event."""
        event = _make_submitted_event()
        result = ingest_canonical_event(event, db)
        assert result["action"] == "APPLIED"

        row = db.execute(
            text("SELECT aggregate_type, aggregate_id, event_type, sequence, tenant_id "
                 "FROM trade_lifecycle_events")
        ).fetchone()

        assert row is not None
        assert row.aggregate_type == "execution"
        assert row.aggregate_id == "ORD-1"
        # ORDER_SUBMITTED → OrderSubmitted (explicit Day38 mapping)
        assert row.event_type == "OrderSubmitted"
        assert row.sequence == 1
        assert row.tenant_id == "tenant-1"

    def test_day38_sequence_independent_of_canonical_sequence(self, db):
        """Day38 sequence is allocated independently of canonical_sequence.

        Uses canonical_sequence=None for both events (no broker sequence
        validation), and verifies Day38 sequences are 1 and 2.
        """
        submit = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED.value, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=None,
            provider_event_id="evt-001",
            order_facts=OrderFacts(broker_order_id="ORD-1", status=CanonicalOrderState.SUBMITTED, total_quantity=100),
            received_at=_NOW + timedelta(seconds=1),
        )
        ingest_canonical_event(submit, db)

        fill = _make_full_fill_event(canonical_sequence=None)
        ingest_canonical_event(fill, db)

        rows = db.execute(
            text("SELECT event_type, sequence FROM trade_lifecycle_events ORDER BY created_at")
        ).fetchall()
        # Two lifecycle events, with Day38 sequences 1 and 2
        assert len(rows) == 2
        assert rows[0].event_type == "OrderSubmitted"
        assert rows[0].sequence == 1
        assert rows[1].event_type == "OrderFilled"
        assert rows[1].sequence == 2

    def test_lifecycle_persistence_compatible_with_day38_duplicate_semantics(self, db):
        """Duplicate canonical event → Day38 is also idempotent (not re-inserted)."""
        event = _make_submitted_event()
        ingest_canonical_event(event, db)

        # Replay identical event
        result = ingest_canonical_event(event, db)
        assert result["action"] == "DUPLICATE_NOOP"

        # Only 1 lifecycle event (Day38 idempotency)
        count = db.execute(text("SELECT COUNT(*) FROM trade_lifecycle_events")).scalar()
        assert count == 1


# ---------------------------------------------------------------------------
# 6. Broker sequence ordering tests
# ---------------------------------------------------------------------------

class TestBrokerSequence:

    def test_sequential_sequences_accepted(self, db):
        """1 → 2 → 3 all accepted."""
        events = []
        for seq in [1, 2, 3]:
            et = BrokerEventType.ORDER_ACCEPTED if seq > 1 else BrokerEventType.ORDER_SUBMITTED
            events.append(make_broker_sync_event(
                tenant_id="tenant-1", broker="broker-test",
                event_type=et, event_version="1.0",
                broker_order_id="ORD-1", canonical_sequence=seq,
                order_facts=OrderFacts(
                    broker_order_id="ORD-1",
                    status=CanonicalOrderState.OPEN,
                    total_quantity=100,
                ),
                received_at=_NOW + timedelta(seconds=seq),
            ))
        for ev in events:
            result = ingest_canonical_event(ev, db)
            assert result["action"] == "APPLIED", f"seq={ev.canonical_sequence} rejected: {result}"

    def test_duplicate_sequence_identical_content_noop(self, db):
        """Sequence 2 → 2 (identical) → no-op."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        acc = _make_submitted_event(canonical_sequence=2)
        ingest_canonical_event(acc, db)

        # Duplicate sequence 2 with identical content
        result = ingest_canonical_event(acc, db)
        assert result["action"] == "DUPLICATE_NOOP"

    def test_duplicate_sequence_different_content_applied(self, db):
        """Same sequence with different fill_facts → different canonical_id → both applied.

        The idempotency layer identifies events by canonical_id (which is
        derived from canonical_sequence AND fill_facts). Two fill events for
        the same order with the same canonical_sequence but different fill
        facts produce different canonical_ids and are treated as distinct
        events.
        """
        # Submit at seq=1
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        # First partial fill at seq=2
        fill1 = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL.value, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_id="fill-001", fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        ingest_canonical_event(fill1, db)

        # Same canonical_sequence but different fill_facts → different canonical_id
        fill2 = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL.value, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=75,
            ),
            fill_facts=FillFacts(fill_id="fill-002", fill_quantity=25, fill_price=101.0,
                                 cumulative_filled_after=75, remaining_after=25),
            received_at=_NOW + timedelta(seconds=3),
        )
        result = ingest_canonical_event(fill2, db)
        # Different fill_id → different canonical_id → both applied
        assert result["action"] == "APPLIED"
        # Two separate projection rows for seq=2
        count = db.execute(
            text("SELECT COUNT(*) FROM broker_order_projection WHERE canonical_sequence = 2"),
        ).scalar()
        assert count == 2

    def test_sequence_gap_rejected(self, db):
        """1 → 3 (gap at 2) → rejected/quarantined."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        gap_event = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_ACCEPTED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.OPEN,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(gap_event, db)
        assert result["action"] == "REJECTED"
        assert "gap" in result["reason"].lower() or "expected" in result["reason"].lower()

    def test_stale_sequence_rejected(self, db):
        """3 → 2 (stale, different content) → rejected."""
        # Sequence 1, 2, 3 applied
        for seq in [1, 2, 3]:
            ev = make_broker_sync_event(
                tenant_id="tenant-1", broker="broker-test",
                event_type=BrokerEventType.ORDER_SUBMITTED if seq == 1 else BrokerEventType.ORDER_ACCEPTED,
                event_version="1.0",
                broker_order_id="ORD-1", canonical_sequence=seq,
                order_facts=OrderFacts(
                    broker_order_id="ORD-1",
                    status=CanonicalOrderState.SUBMITTED,
                    total_quantity=100,
                ),
                received_at=_NOW + timedelta(seconds=seq),
            )
            ingest_canonical_event(ev, db)

        # Stale seq=2 with DIFFERENT content (different total)
        stale = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_ACCEPTED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.OPEN,
                total_quantity=200,  # different from original 100
            ),
            received_at=_NOW + timedelta(seconds=4),
        )
        result = ingest_canonical_event(stale, db)
        assert result["action"] == "REJECTED"
        assert "stale" in result["reason"].lower() or "out-of-order" in result["reason"].lower()

    def test_missing_canonical_sequence_no_fabrication(self, db):
        """canonical_sequence=None → no sequence fabrication.

        Events without canonical_sequence are processed without
        sequence validation; Day38 sequence is independently allocated.
        """
        # Event without canonical_sequence but with fill_facts for identity
        ev1 = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.ORDER_SUBMITTED, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=None,
            provider_event_id="evt-001",  # provides identity
            order_facts=OrderFacts(broker_order_id="ORD-1",
                status=CanonicalOrderState.SUBMITTED, total_quantity=100),
            received_at=_NOW + timedelta(seconds=1),
        )
        result1 = ingest_canonical_event(ev1, db)
        assert result1["action"] == "APPLIED"

        # Second event (no canonical_sequence) with a different provider_event_id
        ev2 = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=None,
            provider_event_id="evt-002",
            order_facts=OrderFacts(broker_order_id="ORD-1",
                status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        result2 = ingest_canonical_event(ev2, db)
        assert result2["action"] == "APPLIED"

        # Day38 sequences should be 1 and 2, not both 1
        rows = db.execute(
            text("SELECT sequence FROM trade_lifecycle_events ORDER BY created_at")
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == 1
        assert rows[1][0] == 2


# ---------------------------------------------------------------------------
# 7. Quantity invariant tests
# ---------------------------------------------------------------------------

class TestQuantityInvariants:

    def test_total_100_cumulative_50_pass(self, db):
        """total=100, cumulative=50 → PASS."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "APPLIED"

    def test_total_100_cumulative_100_pass(self, db):
        """total=100, cumulative=100 → PASS."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        fill = _make_full_fill_event(canonical_sequence=2)
        result = ingest_canonical_event(fill, db)
        assert result["action"] == "APPLIED"
        assert result["normalized_state"]["cumulative_filled"] == 100

    def test_total_100_cumulative_101_rejected(self, db):
        """total=100, cumulative=101 → REJECT."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        overfill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.FULL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.FILLED,
                total_quantity=100, cumulative_filled=101, is_terminal=True,
            ),
            fill_facts=FillFacts(fill_quantity=101, fill_price=100.0,
                                 cumulative_filled_after=101, remaining_after=-1),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(overfill, db)
        assert result["action"] == "REJECTED"
        assert "overfill" in result["reason"].lower() or "exceeds" in result["reason"].lower()

    def test_previous_50_incoming_40_rejected(self, db):
        """previous cumulative=50, incoming cumulative=40 → REJECT."""
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        half_fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=50),
            received_at=_NOW + timedelta(seconds=2),
        )
        ingest_canonical_event(half_fill, db)

        regression = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.FULL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=3,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.FILLED,
                total_quantity=100, cumulative_filled=40, is_terminal=True,
            ),
            fill_facts=FillFacts(fill_quantity=40, fill_price=100.0,
                                 cumulative_filled_after=40, remaining_after=60),
            received_at=_NOW + timedelta(seconds=3),
        )
        result = ingest_canonical_event(regression, db)
        assert result["action"] == "REJECTED"
        assert "regress" in result["reason"].lower()

    def test_negative_fill_quantity_rejected(self, db):
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        neg_fill = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=0,
            ),
            fill_facts=FillFacts(fill_quantity=-5, fill_price=100.0,
                                 cumulative_filled_after=-5, remaining_after=105),
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(neg_fill, db)
        assert result["action"] == "REJECTED"
        assert "negative" in result["reason"].lower()

    def test_remaining_inconsistent_rejected(self, db):
        submit = _make_submitted_event(canonical_sequence=1)
        ingest_canonical_event(submit, db)

        inconsistent = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type=BrokerEventType.PARTIAL_FILL, event_version="1.0",
            broker_order_id="ORD-1", canonical_sequence=2,
            order_facts=OrderFacts(
                broker_order_id="ORD-1", status=CanonicalOrderState.PARTIALLY_FILLED,
                total_quantity=100, cumulative_filled=50,
            ),
            fill_facts=FillFacts(fill_quantity=50, fill_price=100.0,
                                 cumulative_filled_after=50, remaining_after=60),  # should be 50
            received_at=_NOW + timedelta(seconds=2),
        )
        result = ingest_canonical_event(inconsistent, db)
        assert result["action"] == "REJECTED"
        assert "inconsistent" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 8. Communication failure ≠ order rejection
# ---------------------------------------------------------------------------

class TestCommunicationFailure:

    def test_unknown_event_type_rejected_not_mapped_to_rejected_state(self, db):
        """A non-broker-rejection event (e.g. NETWORK_DISCONNECT) is rejected
        by the mapping layer, NOT persisted as REJECTED normalized state.

        Communication failures are NOT mapped to ORDER_REJECTED.
        """
        network_event = make_broker_sync_event(
            tenant_id="tenant-1", broker="broker-test",
            event_type="NETWORK_DISCONNECT",  # not a broker event type
            event_version="1.0",
            broker_order_id="ORD-1",
            canonical_sequence=1,
            order_facts=OrderFacts(
                broker_order_id="ORD-1",
                status=CanonicalOrderState.UNKNOWN,
                total_quantity=100,
            ),
            received_at=_NOW + timedelta(seconds=1),
        )
        result = ingest_canonical_event(network_event, db)
        # NETWORK_DISCONNECT has no Day38 mapping → rejected
        assert result["action"] == "REJECTED"
        assert "NETWORK_DISCONNECT" in result["reason"]
