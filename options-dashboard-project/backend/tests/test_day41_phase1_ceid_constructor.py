"""Day41 Phase 1 — Task1 CEID constructor contract (Option A, Day40.3 §2.5 / Day40.4 §2).

Verifies:
- a supplied canonical_event_id is validated (64 lowercase hex) and vended
  unchanged by canonical_id / event_id
- a CEID event may omit broker_order_id / canonical_sequence / fill_facts /
  provider_event_id in any combination (Invariant S: constructor admissibility)
- all other validation (types, timestamps, metadata) still applies to CEID events
- malformed CEIDs raise
- canonical_event_id=None preserves the legacy algorithm byte-for-byte
  (existing suites are the primary compatibility evidence; the equality
  property is asserted here directly)
"""
from __future__ import annotations

import hashlib

import pytest

from app.broker_sync import (
    BrokerEventSourceMode,
    BrokerEventType,
    BrokerSyncEvent,
    FillFacts,
    OrderFacts,
    make_broker_sync_event,
)

OCCURRED_AT = None  # replaced lazily (module-level datetime keeps parity with Task1 suite)


from datetime import datetime, timezone

OCCURRED_AT = datetime(2026, 9, 8, 10, 30, 0, tzinfo=timezone.utc)
RECEIVED_AT = datetime(2026, 9, 8, 10, 30, 1, tzinfo=timezone.utc)

CEID = "a" * 64
CEID2 = "b" * 64


def _legacy_defaults() -> dict:
    return dict(
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


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CEID constructor acceptance
# ---------------------------------------------------------------------------

def test_ceid_only_event_constructs_without_any_legacy_discriminator() -> None:
    """CON-01: CEID + no provider id, no order id, no seq, no fills is legal."""
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_ACCEPTED.value,
        event_version="1.0",
        received_at=RECEIVED_AT,
        canonical_event_id=CEID,
    )
    assert ev.canonical_event_id == CEID
    assert ev.canonical_id == CEID
    assert ev.event_id == CEID


def test_ceid_is_vended_unchanged_even_with_legacy_fields_present() -> None:
    ev = make_broker_sync_event(
        **_legacy_defaults(),
        canonical_event_id=CEID,
    )
    assert ev.canonical_id == CEID


def test_ceid_with_broker_order_id_and_sequence_constructs() -> None:
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.PARTIAL_FILL.value,
        event_version="1.0",
        event_timestamp=OCCURRED_AT,
        received_at=RECEIVED_AT,
        broker_order_id="upstox-ord-1",
        canonical_sequence=3,
        order_facts=OrderFacts(broker_order_id="upstox-ord-1"),
        canonical_event_id=CEID,
    )
    assert ev.canonical_id == CEID


def test_ceid_with_fill_facts_constructs() -> None:
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.FULL_FILL.value,
        event_version="1.0",
        event_timestamp=OCCURRED_AT,
        received_at=RECEIVED_AT,
        broker_order_id="upstox-ord-2",
        fill_facts=FillFacts(fill_id="t-1", fill_quantity=5, fill_price=100.0),
        canonical_event_id=CEID,
    )
    assert ev.canonical_id == CEID


# ---------------------------------------------------------------------------
# CEID format enforcement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "A" * 64,                # uppercase
        "g" * 64,                # non-hex
        "a" * 63,                # short
        "a" * 65,                # long
        "",                      # empty string (falls into falsy -> treated as None? NO: explicit None check)
        "a" * 32,                # 32 hex (SHA-1-style length)
        "zzzz",                  # garbage
    ],
)
def test_malformed_ceid_raises(bad: str) -> None:
    """CON-02: non-64-lowercase-hex CEIDs are rejected."""
    with pytest.raises(ValueError, match="canonical_event_id"):
        make_broker_sync_event(
            tenant_id="tenant-1",
            broker="UPSTOX",
            event_type=BrokerEventType.ORDER_ACCEPTED.value,
            event_version="1.0",
            received_at=RECEIVED_AT,
            canonical_event_id=bad,
        )


def test_empty_string_ceid_raises() -> None:
    """'' is not None: it must be rejected, not treated as absent."""
    with pytest.raises(ValueError, match="canonical_event_id"):
        make_broker_sync_event(
            tenant_id="tenant-1",
            broker="UPSTOX",
            event_type=BrokerEventType.ORDER_ACCEPTED.value,
            event_version="1.0",
            received_at=RECEIVED_AT,
            canonical_event_id="",
        )


def test_non_string_ceid_raises() -> None:
    with pytest.raises(ValueError, match="canonical_event_id"):
        make_broker_sync_event(
            tenant_id="tenant-1",
            broker="UPSTOX",
            event_type=BrokerEventType.ORDER_ACCEPTED.value,
            event_version="1.0",
            received_at=RECEIVED_AT,
            canonical_event_id=123,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Other validation still applies to CEID events
# ---------------------------------------------------------------------------

def test_ceid_does_not_skip_non_identity_validation() -> None:
    """Naive received_at must still raise for a CEID event (Day40.4 §2.2 steps 1-6)."""
    naive = datetime(2026, 9, 8, 10, 30, 0)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        make_broker_sync_event(
            tenant_id="tenant-1",
            broker="UPSTOX",
            event_type=BrokerEventType.ORDER_ACCEPTED.value,
            event_version="1.0",
            received_at=naive,
            canonical_event_id=CEID,
        )


def test_ceid_does_not_skip_type_validation() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        make_broker_sync_event(
            tenant_id="",
            broker="UPSTOX",
            event_type=BrokerEventType.ORDER_ACCEPTED.value,
            event_version="1.0",
            received_at=RECEIVED_AT,
            canonical_event_id=CEID,
        )


# ---------------------------------------------------------------------------
# Legacy path preserved byte-for-byte
# ---------------------------------------------------------------------------

def test_none_ceid_legacy_provider_event_id_formula_unchanged() -> None:
    ev = make_broker_sync_event(**_legacy_defaults())
    expected = _sha256_hex(
        "\x1f".join(
            ["tenant-1", "UPSTOX", "upstox-evt-123", BrokerEventType.ORDER_SUBMITTED.value]
        )
    )
    assert ev.canonical_event_id is None
    assert ev.canonical_id == expected


def test_none_ceid_fallback_formula_unchanged() -> None:
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.PARTIAL_FILL.value,
        event_version="1.0",
        event_timestamp=OCCURRED_AT,
        received_at=RECEIVED_AT,
        broker_order_id="ord-9",
        canonical_sequence=7,
    )
    expected = _sha256_hex(
        "\x1f".join(["tenant-1", "UPSTOX", BrokerEventType.PARTIAL_FILL.value, "ord-9", "7"])
    )
    assert ev.canonical_id == expected


def test_none_ceid_without_discriminators_still_raises() -> None:
    """CON-03: legacy fail-closed behavior is untouched."""
    with pytest.raises(ValueError, match="insufficient deterministic identity"):
        make_broker_sync_event(
            tenant_id="tenant-1",
            broker="UPSTOX",
            event_type=BrokerEventType.ORDER_ACCEPTED.value,
            event_version="1.0",
            received_at=RECEIVED_AT,
        )


def test_two_ceid_events_with_different_ceids_are_distinct_identities() -> None:
    a = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_ACCEPTED.value,
        event_version="1.0",
        received_at=RECEIVED_AT,
        canonical_event_id=CEID,
    )
    b = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_ACCEPTED.value,
        event_version="1.0",
        received_at=RECEIVED_AT,
        canonical_event_id=CEID2,
    )
    assert a.canonical_id != b.canonical_id


def test_two_constructions_same_ceid_same_content_vend_same_identity() -> None:
    kwargs = dict(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_ACCEPTED.value,
        event_version="1.0",
        received_at=RECEIVED_AT,
        canonical_event_id=CEID,
    )
    assert make_broker_sync_event(**kwargs).canonical_id == make_broker_sync_event(**kwargs).canonical_id


def test_ceid_event_is_frozen_and_canonical_event_id_is_immutable() -> None:
    ev = make_broker_sync_event(
        tenant_id="tenant-1",
        broker="UPSTOX",
        event_type=BrokerEventType.ORDER_ACCEPTED.value,
        event_version="1.0",
        received_at=RECEIVED_AT,
        canonical_event_id=CEID,
    )
    with pytest.raises(Exception):
        ev.canonical_event_id = CEID2  # type: ignore[misc]
