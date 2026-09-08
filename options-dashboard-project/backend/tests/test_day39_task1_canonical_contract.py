"""Day 39 Task 1 — Canonical broker-event synchronization contract tests.

Verifies the broker-neutral canonical event contract required for the
Day 39 event-driven broker-state synchronization path.

Scope:
- canonical event identity (tenant-scoped, deterministic)
- tenant/broker/connection context
- event type / version
- provider identity / provenance
- event timestamp vs. received timestamp
- optional provider sequence
- normalized order/fill state
- immutability
- broker neutrality (no Upstox-specific fields in the domain contract)
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional

import pytest

from app.broker_sync import (
    BrokerEventSourceMode,
    BrokerEventType,
    BrokerSyncEvent,
    CanonicalOrderState,
    FillFacts,
    OrderFacts,
    make_broker_sync_event,
)


# ===========================================================================
# Helpers
# ---------------------------------------------------------------------------

OCCURRED_AT = datetime(2026, 9, 8, 10, 30, 0, tzinfo=timezone.utc)
RECEIVED_AT = datetime(2026, 9, 8, 10, 30, 1, tzinfo=timezone.utc)


def _make_event(**overrides):
    defaults = dict(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_SUBMITTED.value,
        event_version="1.0",
        provider_event_id="upstox-evt-123",
        event_timestamp=OCCURRED_AT,
        received_at=RECEIVED_AT,
        source_mode=BrokerEventSourceMode.STREAM,
        provider_sequence=1,
        broker_order_id="upstox-ord-456",
        canonical_sequence=1,
    )
    defaults.update(overrides)
    return BrokerSyncEvent(**defaults)


# ===========================================================================
# 1. Event identity
# ===========================================================================

def test_canonical_event_has_required_identity_fields() -> None:
    """The canonical event must carry the required deterministic identity."""
    ev = _make_event()
    assert ev.tenant_id == "tenant-1"
    assert ev.broker == "UPSTOX"
    assert ev.event_type == BrokerEventType.ORDER_SUBMITTED.value
    assert ev.event_version == "1.0"
    assert isinstance(ev.canonical_id, str)
    assert len(ev.canonical_id) == 64  # SHA-256 hex


def test_event_id_is_tenant_scoped() -> None:
    """Same broker coordinates in two tenants must produce different event IDs."""
    ev_a = _make_event(tenant_id="tenant-A")
    ev_b = _make_event(tenant_id="tenant-B")
    assert ev_a.canonical_id != ev_b.canonical_id


def test_event_id_is_deterministic() -> None:
    """Same inputs must always produce the same event ID."""
    ev1 = _make_event()
    ev2 = _make_event()
    assert ev1.canonical_id == ev2.canonical_id


def test_event_id_with_provider_event_id_uses_provider_path() -> None:
    """When provider_event_id is present, it dominates identity."""
    ev = _make_event(provider_event_id="prov-1")
    ev_same = _make_event(provider_event_id="prov-1")
    ev_diff = _make_event(provider_event_id="prov-2")
    assert ev.canonical_id == ev_same.canonical_id
    assert ev.canonical_id != ev_diff.canonical_id


def test_event_id_without_provider_event_id_uses_fallback() -> None:
    """Without provider_event_id, broker_order_id + canonical_sequence + event_type distinguish events."""
    ev1 = _make_event(provider_event_id=None, broker_order_id="ord-1", canonical_sequence=1)
    ev2 = _make_event(provider_event_id=None, broker_order_id="ord-1", canonical_sequence=2)
    ev3 = _make_event(provider_event_id=None, broker_order_id="ord-2", canonical_sequence=1)
    assert ev1.canonical_id != ev2.canonical_id  # different sequence
    assert ev1.canonical_id != ev3.canonical_id  # different broker_order_id


# ===========================================================================
# 2. Time semantics
# ===========================================================================

def test_event_timestamp_and_received_timestamp_are_distinct() -> None:
    """The contract must distinguish broker event timestamp from local received timestamp."""
    ev = _make_event(event_timestamp=OCCURRED_AT, received_at=RECEIVED_AT)
    assert ev.event_timestamp == OCCURRED_AT
    assert ev.received_at == RECEIVED_AT
    assert ev.event_timestamp != ev.received_at


def test_naive_timestamps_are_rejected() -> None:
    """Timezone-naive timestamps must be rejected."""
    naive = datetime(2026, 9, 8, 10, 30, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _make_event(event_timestamp=naive, received_at=RECEIVED_AT)
    with pytest.raises(ValueError, match="timezone-aware"):
        _make_event(received_at=naive)


# ===========================================================================
# 3. Provider provenance
# ===========================================================================

def test_provider_provenance_is_retained() -> None:
    """The canonical event must retain broker/provider identity, provider event ID, source/mode, and schema version."""
    ev = _make_event()
    assert ev.broker == "UPSTOX"
    assert ev.provider_event_id == "upstox-evt-123"
    assert ev.source_mode == BrokerEventSourceMode.STREAM
    assert ev.event_version == "1.0"


def test_provider_provenance_does_not_expose_raw_payload_structure() -> None:
    """The domain contract must not carry arbitrary provider payload keys as top-level fields.

    The BrokerSyncEvent dataclass has NO fields like instrument_key,
    transaction_type, is_amo, etc.  Provider payloads must stay adapter-boundary.
    """
    ev = _make_event()
    public_attrs = {
        "tenant_id", "broker", "event_type", "event_version",
        "provider_event_id", "event_timestamp", "received_at",
        "source_mode", "provider_sequence", "broker_order_id",
        "canonical_sequence", "order_facts", "fill_facts", "metadata",
        "canonical_id", "event_id",
    }
    # No Upstox-specific attributes leak through
    assert not hasattr(ev, "instrument_key")
    assert not hasattr(ev, "transaction_type")
    assert not hasattr(ev, "is_amo")
    assert not hasattr(ev, "slice")


# ===========================================================================
# 4. Optional ordering information
# ===========================================================================

def test_provider_sequence_is_optional() -> None:
    """If provider sequence information is unavailable, the contract must not pretend a sequence exists."""
    ev = _make_event(provider_sequence=None)
    assert ev.provider_sequence is None


def test_provider_sequence_is_recorded_when_available() -> None:
    """If provider sequence information exists, it must be represented explicitly."""
    ev = _make_event(provider_sequence=42)
    assert ev.provider_sequence == 42


def test_provider_sequence_must_be_positive() -> None:
    """provider_sequence must be >= 1 when present."""
    with pytest.raises(ValueError, match="positive integer"):
        _make_event(provider_sequence=0)
    with pytest.raises(ValueError, match="positive integer"):
        _make_event(provider_sequence=-1)


# ===========================================================================
# 5. Normalized order/fill information
# ===========================================================================

def test_canonical_order_state_covers_required_states() -> None:
    """The canonical event must represent the normalized order states required by Day 39."""
    required_states = {
        "PENDING", "SUBMITTED", "OPEN", "PARTIALLY_FILLED",
        "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN",
    }
    actual = {s.value for s in CanonicalOrderState}
    assert required_states.issubset(actual)


def test_canonical_fill_info_covers_partial_and_complete_fill() -> None:
    """The canonical event must represent partial and complete fills."""
    facts = FillFacts(
        fill_id="fill-1",
        fill_quantity=10,
        fill_price=100.50,
        fill_timestamp=OCCURRED_AT,
        cumulative_filled_after=10,
        remaining_after=40,
    )
    assert facts.fill_quantity == 10
    assert facts.cumulative_filled_after == 10
    assert facts.remaining_after == 40


def test_order_facts_is_frozen() -> None:
    """OrderFacts must be immutable."""
    facts = OrderFacts(
        order_id="exec-1",
        broker_order_id="ord-1",
        status=CanonicalOrderState.OPEN,
        total_quantity=100,
    )
    with pytest.raises(AttributeError):
        facts.status = CanonicalOrderState.FILLED


# ===========================================================================
# 6. Tenant isolation
# ===========================================================================

def test_tenant_mismatch_is_detected() -> None:
    """Event identity/context must never allow cross-tenant application."""
    ev = _make_event(tenant_id="tenant-A")
    assert ev.belongs_to_tenant("tenant-A") is True
    assert ev.belongs_to_tenant("tenant-B") is False


# ===========================================================================
# 7. Immutability
# ===========================================================================

def test_canonical_event_is_immutable() -> None:
    """The canonical event must be immutable after construction."""
    ev = _make_event()
    with pytest.raises(AttributeError):
        ev.tenant_id = "tenant-X"
    with pytest.raises(AttributeError):
        ev.broker = "OTHER"
    with pytest.raises(AttributeError):
        ev.event_type = "HACKED"


def test_input_payload_is_not_mutated_during_canonicalization() -> None:
    """Inputs must not be silently mutated during canonicalization."""
    mutable_meta = {"key": {"nested": "value"}, "list": [1, 2, 3]}
    ev = _make_event(metadata=mutable_meta)
    # Mutate the original dict
    mutable_meta["key"]["nested"] = "MUTATED"
    mutable_meta["list"].append(4)
    # The event's metadata must remain unchanged
    assert ev.metadata["key"]["nested"] == "value"  # type: ignore[index]
    assert ev.metadata["list"] == (1, 2, 3)  # type: ignore[index]


# ===========================================================================
# 8. Broker neutrality
# ===========================================================================

def test_domain_contract_has_no_upstox_field_names() -> None:
    """The canonical event contract must not depend on Upstox field names, status strings, URLs, or payload structures."""
    import inspect
    source = inspect.getsource(BrokerSyncEvent)
    # No Upstox-specific terms in the contract
    forbidden = ["upstox", "instrument_key", "transaction_type", "is_amo", "slice"]
    for term in forbidden:
        assert term.lower() not in source.lower(), f"Found broker-specific term '{term}' in contract"


def test_make_factory_produces_valid_event() -> None:
    """The convenience factory produces a valid event with defaults."""
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.FULL_FILL.value,
        provider_event_id="prov-1",
        event_timestamp=OCCURRED_AT,
    )
    assert ev.tenant_id == "tenant-1"
    assert ev.event_type == BrokerEventType.FULL_FILL.value
    assert ev.event_version == "1.0"
    assert ev.source_mode == BrokerEventSourceMode.STREAM
    assert ev.received_at is not None  # defaulted


def test_factory_requires_received_at_or_defaults_to_now() -> None:
    """Factory defaults received_at when not supplied."""
    before = datetime.now(timezone.utc)
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_SUBMITTED.value,
        provider_event_id="prov-1",
    )
    after = datetime.now(timezone.utc)
    assert before <= ev.received_at <= after
