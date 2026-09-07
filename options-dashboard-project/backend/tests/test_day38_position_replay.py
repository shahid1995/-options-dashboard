"""Day 38 Task 4: Position lifecycle replay + position sequence semantics tests.

TDD: RED first (module does not exist yet), then GREEN.

Covers the approved Task 4 boundary (position lifecycle ONLY):
- signed quantity_delta reconstruction (net = sum of deltas for an instance)
- PositionIdentity = (user_id, symbol, expiry, strike, option_type), NOT
  execution-owned; execution_id is attribution only
- lifecycle instances: OPEN -> CLOSED, terminal for the instance; a later
  PositionOpened deterministically starts a NEW instance (never CLOSED->OPEN
  on the same instance)
- zero-crossing decomposition (close-to-zero then open-of-remainder)
- strict sequence/identity/terminal/quantity validation
- deterministic, side-effect-free, input-preserving replay
- position_sequence allocation against the approved Task 1 allocator
  (SQLite deterministic checks; PostgreSQL concurrency is a separate file)
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.trade_lifecycle.envelope import PositionIdentity, TradeLifecycleEventEnvelope
from app.trade_lifecycle.persistence import allocate_position_sequence
from app.trade_lifecycle.replay import (
    LifecycleReplayError,
    LifecycleSequenceError,
    ReplaySequenceGap,
    ReplaySecurityError,
    ReplayUnknownVersion,
    ReplayCorruptPayload,
)
from app.trade_lifecycle.position_replay import (
    PositionLifecycleState,
    PositionStatus,
    decompose_position_delta,
    replay_position_events,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT = "user-1"
OCCURRED_AT = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)

DEFAULT_IDENTITY = dict(
    user_id="user-1",
    symbol="NIFTY",
    expiry="2026-12-31",
    strike=24000.0,
    option_type="CE",
)


def position_event(event_type, sequence, quantity_delta, *,
                   position_sequence=1, identity=None, tenant_id=TENANT,
                   aggregate_id="exec-1", event_version="1.0"):
    """Build a Task 2 lifecycle envelope carrying a position contribution.

    ``aggregate_id`` is execution attribution/provenance only — position is
    NOT execution-owned, so different events may carry different executions.
    """
    ident = PositionIdentity(**(identity or DEFAULT_IDENTITY))
    return TradeLifecycleEventEnvelope(
        tenant_id=tenant_id,
        aggregate_type="TradeLifecycle",
        aggregate_id=aggregate_id,
        event_type=event_type,
        event_version=event_version,
        sequence=sequence,
        occurred_at=OCCURRED_AT,
        payload={"symbol": ident.symbol},
        position_sequence=position_sequence,
        position_identity=ident,
        quantity_delta=quantity_delta,
    )


def net_zero_close_stream():
    """Open +10, reduce -2, close -8 -> net 0, CLOSED."""
    return [
        position_event("PositionOpened", 1, +10),
        position_event("PositionUpdated", 2, -2),
        position_event("PositionClosed", 3, -8),
    ]


# ---------------------------------------------------------------------------
# 1. Signed delta reconstruction
# ---------------------------------------------------------------------------

def test_position_replay_sums_signed_quantity_deltas():
    events = net_zero_close_stream()
    state = replay_position_events(events)
    assert state.net_quantity == 0
    assert state.status == PositionStatus.CLOSED


def test_position_replay_open_instance_state():
    events = [
        position_event("PositionOpened", 1, +10),
        position_event("PositionUpdated", 2, -2),
    ]
    state = replay_position_events(events)
    assert state.net_quantity == 8
    assert state.status == PositionStatus.OPEN


def test_position_replay_short_position():
    events = [
        position_event("PositionOpened", 1, -10),
        position_event("PositionClosed", 2, +10),
    ]
    state = replay_position_events(events)
    assert state.net_quantity == 0
    assert state.status == PositionStatus.CLOSED


# ---------------------------------------------------------------------------
# 2. Lifecycle reuse (closed instance is terminal; new instance may open)
# ---------------------------------------------------------------------------

def test_closed_position_identity_can_open_new_sequence():
    first = [position_event("PositionOpened", 1, +10, position_sequence=1),
             position_event("PositionClosed", 2, -10, position_sequence=1)]
    second = [position_event("PositionOpened", 1, +5, position_sequence=2)]
    assert replay_position_events(first).status == PositionStatus.CLOSED
    reopened = replay_position_events(second)
    assert reopened.status == PositionStatus.OPEN
    assert reopened.net_quantity == 5
    assert reopened.position_sequence == 2


def test_closed_instance_cannot_reopen_within_same_stream():
    events = [
        position_event("PositionOpened", 1, +10, position_sequence=1),
        position_event("PositionClosed", 2, -10, position_sequence=1),
        # Reusing position_sequence=1 on a CLOSED instance is invalid:
        position_event("PositionOpened", 3, +5, position_sequence=1),
    ]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_two_instances_flow_in_one_stream():
    events = [
        position_event("PositionOpened", 1, +10, position_sequence=1),
        position_event("PositionClosed", 2, -10, position_sequence=1),
        position_event("PositionOpened", 3, +5, position_sequence=2),
    ]
    state = replay_position_events(events)
    assert state.status == PositionStatus.OPEN
    assert state.net_quantity == 5
    assert state.position_sequence == 2


# ---------------------------------------------------------------------------
# 3. Zero-crossing decomposition
# ---------------------------------------------------------------------------

def test_zero_crossing_is_close_then_open_new_lifecycle():
    result = decompose_position_delta(current_quantity=10, requested_delta=-15)
    assert result == [
        ("PositionClosed", -10),
        ("PositionOpened", -5),
    ]


def test_reverse_zero_crossing_is_close_then_open_new_lifecycle():
    result = decompose_position_delta(current_quantity=-10, requested_delta=+15)
    assert result == [
        ("PositionClosed", +10),
        ("PositionOpened", +5),
    ]


def test_exact_opposite_delta_decomposes_to_close_only():
    result = decompose_position_delta(current_quantity=10, requested_delta=-10)
    assert result == [("PositionClosed", -10)]
    result = decompose_position_delta(current_quantity=-10, requested_delta=+10)
    assert result == [("PositionClosed", +10)]


def test_reduction_within_instance_is_not_a_crossing():
    assert decompose_position_delta(current_quantity=10, requested_delta=-5) is None
    assert decompose_position_delta(current_quantity=-10, requested_delta=+5) is None


def test_same_direction_delta_is_not_a_crossing():
    assert decompose_position_delta(current_quantity=10, requested_delta=+15) is None
    assert decompose_position_delta(current_quantity=-10, requested_delta=-15) is None


def test_opening_from_flat_is_not_a_crossing():
    assert decompose_position_delta(current_quantity=0, requested_delta=+5) is None


def test_decompose_rejects_zero_requested_delta():
    with pytest.raises(ValueError):
        decompose_position_delta(current_quantity=10, requested_delta=0)


# ---------------------------------------------------------------------------
# 4. Strict quantity invariants during replay
# ---------------------------------------------------------------------------

def test_close_requires_exact_zero():
    # Open +10 then Close -5 leaves +5 open -> reject.
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionClosed", 2, -5)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_position_opened_requires_nonzero_delta():
    events = [position_event("PositionOpened", 1, 0)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_position_updated_must_not_cross_zero():
    # +10 with -15 crosses zero inside one instance -> reject.
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionUpdated", 2, -15)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_position_updated_must_not_land_exactly_on_zero():
    # Reaching zero must be expressed as PositionClosed, not PositionUpdated.
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionUpdated", 2, -10)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


# ---------------------------------------------------------------------------
# 5. Terminal-state protection
# ---------------------------------------------------------------------------

def test_mutation_after_close_is_rejected():
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionClosed", 2, -10),
              position_event("PositionUpdated", 3, +5)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_update_on_closed_instance_is_rejected():
    events = [position_event("PositionOpened", 1, +10, position_sequence=1),
              position_event("PositionClosed", 2, -10, position_sequence=1),
              position_event("PositionUpdated", 3, +5, position_sequence=1)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_second_position_opened_while_instance_open_is_rejected():
    events = [position_event("PositionOpened", 1, +10, position_sequence=1),
              position_event("PositionOpened", 2, +5, position_sequence=2)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_update_must_target_the_open_instance():
    # position_sequence=2 is not the open instance (1) -> reject.
    events = [position_event("PositionOpened", 1, +10, position_sequence=1),
              position_event("PositionUpdated", 2, -2, position_sequence=2)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


# ---------------------------------------------------------------------------
# 6. Sequence validation
# ---------------------------------------------------------------------------

def test_position_replay_rejects_sequence_gap():
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionClosed", 3, -10)]
    with pytest.raises(LifecycleSequenceError):
        replay_position_events(events)


def test_position_replay_gap_is_replay_sequence_gap():
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionClosed", 3, -10)]
    with pytest.raises(ReplaySequenceGap):
        replay_position_events(events)


def test_position_replay_rejects_out_of_order_stream():
    events = [position_event("PositionClosed", 2, -10),
              position_event("PositionOpened", 1, +10)]
    with pytest.raises(LifecycleSequenceError):
        replay_position_events(events)


def test_position_replay_rejects_empty_stream():
    with pytest.raises(LifecycleSequenceError):
        replay_position_events([])


def test_position_replay_rejects_unknown_event_version():
    events = [position_event("PositionOpened", 1, +10, event_version="99.0")]
    with pytest.raises(ReplayUnknownVersion):
        replay_position_events(events)


# ---------------------------------------------------------------------------
# 7. Identity validation (fail closed)
# ---------------------------------------------------------------------------

def test_position_replay_rejects_symbol_mismatch():
    other = dict(DEFAULT_IDENTITY, symbol="BANKNIFTY")
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionUpdated", 2, -2, identity=other)]
    with pytest.raises(ReplaySecurityError):
        replay_position_events(events)


def test_position_replay_rejects_option_type_mismatch():
    other = dict(DEFAULT_IDENTITY, option_type="PE")
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionClosed", 2, -10, identity=other)]
    with pytest.raises(ReplaySecurityError):
        replay_position_events(events)


def test_position_replay_rejects_tenant_mismatch():
    events = [position_event("PositionOpened", 1, +10),
              position_event("PositionClosed", 2, -10, tenant_id="user-2")]
    with pytest.raises(ReplaySecurityError):
        replay_position_events(events)


def test_position_replay_rejects_execution_event_types():
    events = [position_event("TradeIntentCreated", 1, None)]
    with pytest.raises(LifecycleReplayError):
        replay_position_events(events)


def test_position_replay_requires_position_identity_on_envelope():
    ev = TradeLifecycleEventEnvelope(
        tenant_id=TENANT,
        aggregate_type="TradeLifecycle",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        sequence=1,
        occurred_at=OCCURRED_AT,
        payload={},
        position_identity=None,
        quantity_delta=10,
        position_sequence=1,
    )
    with pytest.raises(ReplayCorruptPayload):
        replay_position_events([ev])


# ---------------------------------------------------------------------------
# 8. Deterministic replay / purity / input immutability
# ---------------------------------------------------------------------------

def test_position_replay_is_deterministic():
    events = net_zero_close_stream()
    state_a = replay_position_events(events)
    state_b = replay_position_events(events)
    assert state_a == state_b
    assert state_a is not state_b


def test_position_replay_does_not_mutate_inputs():
    events = net_zero_close_stream()
    before = [
        (e.event_type, e.sequence, e.quantity_delta, e.position_sequence,
         e.position_identity) for e in events
    ]
    replay_position_events(events)
    after = [
        (e.event_type, e.sequence, e.quantity_delta, e.position_sequence,
         e.position_identity) for e in events
    ]
    assert after == before


def test_position_replay_state_exposes_projection():
    state = replay_position_events(net_zero_close_stream())
    assert isinstance(state, PositionLifecycleState)
    assert state.position_identity == PositionIdentity(**DEFAULT_IDENTITY)
    assert state.tenant_id == TENANT
    assert state.last_sequence == 3


# ---------------------------------------------------------------------------
# 9. Position sequence allocation (deterministic SQLite)
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture()
def fresh_db():
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


def _alloc(db, tenant="user-1", user="user-1", symbol="NIFTY", expiry="2026-12-31",
           strike=24000.0, option_type="CE"):
    return allocate_position_sequence(
        db=db, tenant_id=tenant, user_id=user, symbol=symbol, expiry=expiry,
        strike=strike, option_type=option_type,
    )


def test_position_sequence_allocation_is_monotonic(fresh_db):
    db = TestSession()
    assert _alloc(db) == 1
    assert _alloc(db) == 2
    assert _alloc(db) == 3
    db.commit()
    db.close()


def test_position_sequence_rollback_does_not_burn(fresh_db):
    db = TestSession()
    assert _alloc(db) == 1
    db.rollback()
    assert _alloc(db) == 1  # rollback: the anchor increment is not burned
    db.commit()
    db.close()


def test_position_sequence_scoped_by_complete_identity(fresh_db):
    db = TestSession()
    assert _alloc(db) == 1                       # NIFTY 24000 CE
    assert _alloc(db, option_type="PE") == 1     # different identity -> independent
    assert _alloc(db, symbol="BANKNIFTY") == 1   # different symbol -> independent
    assert _alloc(db) == 2                       # same identity advances
    db.commit()
    db.close()


def test_position_sequence_tenant_isolation(fresh_db):
    db = TestSession()
    assert _alloc(db, tenant="tenant-A") == 1
    assert _alloc(db, tenant="tenant-B") == 1  # independent tenant anchor
    assert _alloc(db, tenant="tenant-A") == 2
    db.commit()
    db.close()
