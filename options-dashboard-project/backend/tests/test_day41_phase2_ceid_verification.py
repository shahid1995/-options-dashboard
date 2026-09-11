"""Day41 Phase 2 — Task2 CEID verification hook (Day40.4 §3.4).

Verifies the pre-idempotency CEID verification:
- metadata["strikenova"] present + matching CEID  -> normal path (applied)
- metadata present + mismatching CEID             -> REJECTED (canonical identity mismatch)
- incomplete metadata block                       -> REJECTED
- metadata present but no canonical_event_id      -> REJECTED
- legacy events without the metadata block        -> unchanged path
- same CEID + same content                        -> DUPLICATE_NOOP
- same CEID + conflicting Task2 fingerprint       -> CONFLICT

Runs against the committed Task2 pipeline (SQLite, same harness as the
Day39 Task2 suite) to prove the hook integrates with real idempotency.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.broker_sync import (
    BrokerEventType,
    BrokerEventSourceMode,
    BrokerSyncEvent,
    CanonicalOrderState,
    OrderFacts,
    compute_ceid,
    compute_d1,
    make_broker_sync_event,
)
from app.broker_sync.ingestion import IngestionError, ingest_canonical_event
from app.broker_sync.models import BrokerSyncIdempotency

# ---------------------------------------------------------------------------
# Test database setup (mirrors the Day39 Task2 suite)
# ---------------------------------------------------------------------------

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
    import app.trade_lifecycle.persistence  # noqa: F401

    Base.metadata.create_all(_engine)
    session = _TestSessionLocal()
    _seed_app_order(session, "ORD-CEID")
    session.commit()
    yield session
    session.rollback()
    session.close()
    Base.metadata.drop_all(_engine)


def _strikenova_meta(d1: str, fp: str) -> dict:
    return {
        "strikenova": {
            "d1": d1,
            "content_fingerprint": fp,
            "d1_version": "D1v1",
            "fp_version": "FPv2",
        }
    }


def _ceid_event(
    *,
    ceid: str | None,
    metadata: dict | None,
    event_type: str = BrokerEventType.ORDER_ACCEPTED.value,
    canonical_sequence: int = 1,
) -> BrokerSyncEvent:
    return make_broker_sync_event(
        tenant_id="tenant-1",
        broker="broker-test",
        event_type=event_type,
        event_version="1.0",
        broker_order_id="ORD-CEID",
        canonical_sequence=canonical_sequence,
        received_at=_NOW + timedelta(seconds=2),
        order_facts=OrderFacts(
            broker_order_id="ORD-CEID",
            order_id="ORD-CEID",
            status=CanonicalOrderState.OPEN,
        ),
        metadata=metadata,
        canonical_event_id=ceid,
    )


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

def test_compute_d1_order_formula() -> None:
    expected_d1 = compute_d1(
        tenant_id="tenant-1", broker="UPSTOX",
        order_id="240108010445130", event_type=BrokerEventType.ORDER_ACCEPTED,
    )
    # Deterministic and distinct from other orders
    other = compute_d1(
        tenant_id="tenant-1", broker="UPSTOX",
        order_id="240108010445131", event_type=BrokerEventType.ORDER_ACCEPTED,
    )
    assert expected_d1 != other
    assert len(expected_d1) == 64


def test_compute_d1_fill_formula_includes_trade_id() -> None:
    order_d1 = compute_d1(
        tenant_id="t", broker="UPSTOX", order_id="O1",
        event_type=BrokerEventType.FULL_FILL,
    )
    fill_d1 = compute_d1(
        tenant_id="t", broker="UPSTOX", order_id="O1",
        event_type=BrokerEventType.FULL_FILL, trade_id="50091502",
    )
    assert order_d1 != fill_d1


def test_compute_ceid_known_vector() -> None:
    """CEID = SHA256('CEIDv1:' || US || d1 || US || fp) — machine-checked vector."""
    d1 = "d" * 64
    fp = "f" * 64
    import hashlib
    expected = hashlib.sha256(("CEIDv1:\x1f" + d1 + "\x1f" + fp).encode("utf-8")).hexdigest()
    assert compute_ceid(d1, fp) == expected


# ---------------------------------------------------------------------------
# Verification hook behavior
# ---------------------------------------------------------------------------

def _derive_fp_for(event: BrokerSyncEvent) -> str:
    from app.broker_sync.ingestion import _content_fingerprint
    return _content_fingerprint(event)


def test_valid_ceid_event_applies(db) -> None:
    ev = _ceid_event(ceid="a" * 64, metadata=None)
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "APPLIED"


def test_matching_ceid_metadata_applies(db) -> None:
    ev = _ceid_event(ceid="a" * 64, metadata=None)
    fp = _derive_fp_for(ev)
    d1 = compute_d1(
        tenant_id="tenant-1", broker="broker-test", order_id="ORD-CEID",
        event_type=BrokerEventType.ORDER_ACCEPTED,
    )
    ev2 = _ceid_event(ceid=compute_ceid(d1, fp), metadata=_strikenova_meta(d1, fp))
    result = ingest_canonical_event(ev2, db, tenant_id="tenant-1")
    assert result["action"] == "APPLIED"


def test_mismatched_ceid_metadata_rejected(db) -> None:
    ev = _ceid_event(ceid="a" * 64, metadata=None)
    fp = _derive_fp_for(ev)
    d1 = compute_d1(
        tenant_id="tenant-1", broker="broker-test", order_id="ORD-CEID",
        event_type=BrokerEventType.ORDER_ACCEPTED,
    )
    # Deliberately wrong CEID (does not match derived)
    wrong_ceid = "b" * 64
    assert wrong_ceid != compute_ceid(d1, fp)
    ev2 = _ceid_event(ceid=wrong_ceid, metadata=_strikenova_meta(d1, fp))
    result = ingest_canonical_event(ev2, db, tenant_id="tenant-1")
    assert result["action"] == "REJECTED"
    assert "canonical identity mismatch" in result["reason"]


def test_incomplete_metadata_block_rejected(db) -> None:
    ev = _ceid_event(
        ceid="a" * 64,
        metadata={"strikenova": {"d1": "d" * 64}},  # missing content_fingerprint
    )
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "REJECTED"
    assert "canonical identity mismatch" in result["reason"]


def test_metadata_without_ceid_rejected(db) -> None:
    d1 = "d" * 64
    fp = "f" * 64
    ev = _ceid_event(ceid=None, metadata=_strikenova_meta(d1, fp))
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "REJECTED"
    assert "canonical identity mismatch" in result["reason"]


def test_metadata_without_strikenova_block_unchanged(db) -> None:
    """Legacy events with unrelated metadata skip verification entirely."""
    ev = _ceid_event(ceid="a" * 64, metadata={"upstox": {"status": "open"}})
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "APPLIED"


def test_legacy_event_without_metadata_unchanged(db) -> None:
    ev = _ceid_event(ceid=None, metadata=None)
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "APPLIED"


# ---------------------------------------------------------------------------
# Idempotency / conflict on the same CEID
# ---------------------------------------------------------------------------

def test_same_ceid_same_content_duplicate_noop(db) -> None:
    d1 = compute_d1(
        tenant_id="tenant-1", broker="broker-test", order_id="ORD-CEID",
        event_type=BrokerEventType.ORDER_ACCEPTED,
    )
    fp = "f" * 64
    ceid = compute_ceid(d1, fp)  # CEID must derive from the metadata block
    ev1 = _ceid_event(ceid=ceid, metadata=_strikenova_meta(d1, fp))
    ev2 = _ceid_event(ceid=ceid, metadata=_strikenova_meta(d1, fp))
    r1 = ingest_canonical_event(ev1, db, tenant_id="tenant-1")
    r2 = ingest_canonical_event(ev2, db, tenant_id="tenant-1")
    assert r1["action"] == "APPLIED"
    assert r2["action"] == "DUPLICATE_NOOP"


def test_same_ceid_conflicting_task2_fingerprint_conflict(db) -> None:
    d1 = compute_d1(
        tenant_id="tenant-1", broker="broker-test", order_id="ORD-CEID",
        event_type=BrokerEventType.ORDER_ACCEPTED,
    )
    # Same CEID and same claimed (d1, fp) metadata block, but the events'
    # actual Task2 content differs (different OrderFacts.status), so the
    # Task2 _content_fingerprint differs while canonical_id is identical.
    fp = "f" * 64
    ceid = compute_ceid(d1, fp)  # CEID must derive from the metadata block
    ev1 = _ceid_event(ceid=ceid, metadata=_strikenova_meta(d1, fp))
    ev2 = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="broker-test",
        event_type=BrokerEventType.ORDER_ACCEPTED.value,
        event_version="1.0",
        broker_order_id="ORD-CEID",
        canonical_sequence=1,
        received_at=_NOW + timedelta(seconds=2),
        order_facts=OrderFacts(
            broker_order_id="ORD-CEID",
            order_id="ORD-CEID",
            status=CanonicalOrderState.SUBMITTED,  # different Task2 content
        ),
        metadata=_strikenova_meta(d1, fp),
        canonical_event_id=ceid,
    )
    r1 = ingest_canonical_event(ev1, db, tenant_id="tenant-1")
    r2 = ingest_canonical_event(ev2, db, tenant_id="tenant-1")
    assert r1["action"] == "APPLIED"
    assert r2["action"] == "CONFLICT"


def test_ceid_verification_precedes_idempotency(db) -> None:
    """A mismatching CEID is REJECTED even if its canonical_id was never seen."""
    d1 = "d" * 64
    fp = "f" * 64
    bad = "e" * 64
    ev = _ceid_event(ceid=bad, metadata=_strikenova_meta(d1, fp))
    result = ingest_canonical_event(ev, db, tenant_id="tenant-1")
    assert result["action"] == "REJECTED"
    row = db.execute(
        select(BrokerSyncIdempotency).where(
            BrokerSyncIdempotency.canonical_id == bad
        )
    ).scalar_one_or_none()
    assert row is None  # nothing recorded before verification
