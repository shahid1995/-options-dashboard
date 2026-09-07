"""Day 38 Task 2: Immutable lifecycle event envelope + canonical identity tests.

TDD: RED first (create these before implementation), then GREEN.

Covers the approved Task2 boundary:
- immutable event envelope (Day37 `@dataclass(frozen=True)` convention)
- defensive copying of payload/metadata mappings (DD-3)
- metadata None vs {} distinction
- deterministic canonical identity (tenant-scoped, byte-compatible with Task1)
- deterministic canonical content (full field set, sorted-key JSON)
- identity vs content separation
- Day37 DomainEvent compatibility (unmodified)
"""

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone, timedelta

import pytest

from app.trade_lifecycle.envelope import (
    PositionIdentity,
    TradeLifecycleEventEnvelope,
    canonical_event_content,
    event_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OCCURRED_AT = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)

POSITION_IDENTITY = PositionIdentity(
    user_id="user-1",
    symbol="NIFTY",
    expiry="2026-12-31",
    strike=24000.0,
    option_type="CE",
)


def make_event(**overrides):
    """Build an envelope with sensible defaults; override any field."""
    base = dict(
        tenant_id="tenant-1",
        aggregate_type="TradeLifecycle",
        aggregate_id="exec-1",
        event_type="PositionOpened",
        event_version="1.0",
        sequence=1,
        position_sequence=1,
        position_identity=POSITION_IDENTITY,
        quantity_delta=10,
        occurred_at=OCCURRED_AT,
        payload={"symbol": "NIFTY"},
        metadata=None,
    )
    base.update(overrides)
    return TradeLifecycleEventEnvelope(**base)


# ---------------------------------------------------------------------------
# 1. Envelope shape and immutability
# ---------------------------------------------------------------------------

def test_event_envelope_contains_explicit_lifecycle_fields():
    event = make_event()
    assert event.tenant_id == "tenant-1"
    assert event.aggregate_type == "TradeLifecycle"
    assert event.aggregate_id == "exec-1"
    assert event.event_type == "PositionOpened"
    assert event.event_version == "1.0"
    assert event.sequence == 1
    assert event.position_sequence == 1
    assert event.position_identity == POSITION_IDENTITY
    assert event.quantity_delta == 10
    assert event.occurred_at == OCCURRED_AT
    assert event.payload == {"symbol": "NIFTY"}
    assert event.metadata is None
    assert event.event_id  # derived, non-empty


def test_envelope_mutation_is_rejected():
    event = make_event()
    with pytest.raises(FrozenInstanceError):
        event.sequence = 2


def test_envelope_rejects_naive_occurred_at():
    with pytest.raises(ValueError):
        make_event(occurred_at=datetime(2026, 6, 15, 10, 30, 0))


def test_envelope_rejects_empty_identity_fields():
    for empty_field in (
        "tenant_id",
        "aggregate_type",
        "aggregate_id",
        "event_type",
        "event_version",
    ):
        with pytest.raises(ValueError):
            make_event(**{empty_field: ""})


def test_envelope_rejects_non_positive_sequences():
    with pytest.raises(ValueError):
        make_event(sequence=0)
    with pytest.raises(ValueError):
        make_event(position_sequence=0)


def test_envelope_rejects_non_mapping_payload():
    with pytest.raises(TypeError):
        make_event(payload="not-a-mapping")


def test_payload_and_metadata_are_defensively_copied():
    payload = {"symbol": "NIFTY"}
    metadata = {"source": "paper_engine"}
    event = make_event(payload=payload, metadata=metadata)
    payload["symbol"] = "MUTATED"
    metadata["source"] = "MUTATED"
    assert event.payload == {"symbol": "NIFTY"}
    assert event.metadata == {"source": "paper_engine"}


# ===========================================================================
# REMEDIATION (Day38 Task2 Finding #3) — deep (nested) immutability
# ===========================================================================

def test_original_nested_dict_mutation_does_not_change_envelope():
    """Mutating the caller's original nested dicts after construction must not
    change the envelope's payload/metadata or canonical content."""
    payload = {"details": {"source": "paper_engine"}}
    metadata = {"tags": ["a", "b"], "context": {"depth": 1}}
    event = make_event(payload=payload, metadata=metadata)
    before = canonical_event_content(event)

    # Mutate the caller's ORIGINAL nested structures after construction.
    payload["details"]["source"] = "changed"
    payload["details"]["extra"] = "x"
    payload["top_level"] = "added"
    metadata["tags"].append("c")
    metadata["context"]["depth"] = 99
    metadata["new_key"] = "y"

    assert event.payload["details"]["source"] == "paper_engine"
    assert event.metadata["context"]["depth"] == 1
    assert list(event.metadata["tags"]) == ["a", "b"]
    assert canonical_event_content(event) == before


def test_nested_mutation_through_envelope_is_rejected():
    """Callers must not be able to mutate nested payload/metadata via the envelope."""
    event = make_event(
        payload={"details": {"source": "paper_engine"}, "tags": ["a", "b"]},
        metadata={"ctx": {"depth": 1}},
    )
    with pytest.raises(TypeError):
        event.payload["details"]["source"] = "changed"  # nested dict write
    with pytest.raises(TypeError):
        event.payload["tags"][0] = "z"  # nested list write
    with pytest.raises(TypeError):
        event.payload["new_top_key"] = "x"  # top-level write
    with pytest.raises(TypeError):
        event.metadata["ctx"]["depth"] = 99  # nested metadata write

    # Structures remain intact after rejected mutations.
    assert event.payload["details"]["source"] == "paper_engine"
    assert list(event.payload["tags"]) == ["a", "b"]
    assert event.metadata["ctx"] == {"depth": 1}


def test_canonical_content_stable_under_original_mutation():
    """Canonical content is construction-time stable even if the caller later
    mutates the nested structures they originally passed in."""
    payload = {"details": {"source": "paper_engine"}}
    event = make_event(payload=payload)
    c1 = canonical_event_content(event)
    payload["details"]["source"] = "hacked"
    c2 = canonical_event_content(event)
    assert c1 == c2


def test_to_domain_event_produces_day37_compatible_envelope():
    from app.domain_events.contracts import DomainEvent

    event = make_event(metadata={"source": "paper_engine"})
    domain_event = event.to_domain_event()
    assert isinstance(domain_event, DomainEvent)
    assert domain_event.event_id == event.event_id
    assert domain_event.event_type == event.event_type
    assert domain_event.tenant_id == event.tenant_id
    assert domain_event.occurred_at == event.occurred_at


# ---------------------------------------------------------------------------
# 2. Deterministic canonical identity (tenant-scoped)
# ---------------------------------------------------------------------------

def test_event_id_deterministic_across_calls():
    e1 = event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 1)
    e2 = event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 1)
    assert e1 == e2


def test_event_id_differs_by_tenant():
    assert event_id("t1", "TradeLifecycle", "exec-1", "PositionOpened", 1) != event_id(
        "t2", "TradeLifecycle", "exec-1", "PositionOpened", 1
    )


def test_event_id_differs_by_aggregate_type_and_id():
    base = event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 1)
    assert base != event_id("tenant-1", "position", "exec-1", "PositionOpened", 1)
    assert base != event_id("tenant-1", "TradeLifecycle", "exec-2", "PositionOpened", 1)


def test_event_id_differs_by_event_type():
    assert event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 1) != event_id(
        "tenant-1", "TradeLifecycle", "exec-1", "PositionClosed", 1
    )


def test_event_id_differs_by_sequence():
    assert event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 1) != event_id(
        "tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 2
    )


def test_event_id_matches_persistence_event_id():
    from app.trade_lifecycle.persistence import event_id as persistence_event_id

    assert event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 7) == (
        persistence_event_id("tenant-1", "TradeLifecycle", "exec-1", "PositionOpened", 7)
    )


def test_event_id_excludes_payload_and_metadata():
    e1 = make_event(payload={"a": 1}, metadata={"m": 1})
    e2 = make_event(payload={"a": 2}, metadata={"m": 2})
    assert e1.event_id == e2.event_id


def test_envelope_event_id_changes_with_identity_fields():
    base = make_event()
    assert make_event(tenant_id="tenant-2").event_id != base.event_id
    assert make_event(aggregate_id="exec-2").event_id != base.event_id
    assert make_event(event_type="PositionClosed").event_id != base.event_id
    assert make_event(sequence=2).event_id != base.event_id


# ---------------------------------------------------------------------------
# 3. Deterministic canonical content
# ---------------------------------------------------------------------------

def test_canonical_content_is_stable_for_same_event():
    assert canonical_event_content(make_event()) == canonical_event_content(make_event())


def test_canonical_content_independent_of_dict_insertion_order():
    a = make_event(payload={"a": 1, "b": 2, "c": 3})
    b = make_event(payload={"c": 3, "b": 2, "a": 1})
    assert canonical_event_content(a) == canonical_event_content(b)
    parsed = json.loads(canonical_event_content(a))
    # Re-serialize the parsed form; keys must already be in sorted order.
    assert canonical_event_content(a) == json.dumps(parsed, sort_keys=True, ensure_ascii=True)


def test_identical_envelopes_have_equal_canonical_content():
    e1 = make_event(metadata={"source": "paper_engine"})
    e2 = make_event(metadata={"source": "paper_engine"})
    assert canonical_event_content(e1) == canonical_event_content(e2)


def test_conflicting_envelopes_have_different_canonical_content():
    e1 = make_event()
    e2 = make_event(quantity_delta=-10)
    assert canonical_event_content(e1) != canonical_event_content(e2)


def test_canonical_content_differs_by_position_sequence():
    assert canonical_event_content(make_event(position_sequence=1)) != canonical_event_content(
        make_event(position_sequence=2)
    )


def test_canonical_content_differs_by_position_identity_field():
    base = make_event()
    variants = [
        PositionIdentity("user-2", "NIFTY", "2026-12-31", 24000.0, "CE"),
        PositionIdentity("user-1", "BANKNIFTY", "2026-12-31", 24000.0, "CE"),
        PositionIdentity("user-1", "NIFTY", "2026-12-24", 24000.0, "CE"),
        PositionIdentity("user-1", "NIFTY", "2026-12-31", 25000.0, "CE"),
        PositionIdentity("user-1", "NIFTY", "2026-12-31", 24000.0, "PE"),
    ]
    for variant in variants:
        assert canonical_event_content(base) != canonical_event_content(
            make_event(position_identity=variant)
        )


def test_canonical_content_differs_by_quantity_delta():
    base = canonical_event_content(make_event(quantity_delta=10))
    assert base != canonical_event_content(make_event(quantity_delta=-10))
    assert base != canonical_event_content(make_event(quantity_delta=0))


def test_canonical_content_differs_by_metadata():
    none_canonical = canonical_event_content(make_event(metadata=None))
    empty_canonical = canonical_event_content(make_event(metadata={}))
    value_canonical = canonical_event_content(make_event(metadata={"source": "paper_engine"}))
    assert none_canonical != value_canonical
    assert none_canonical != empty_canonical
    assert empty_canonical != value_canonical


def test_metadata_none_is_not_empty_dict():
    assert make_event(metadata=None).metadata is None
    assert make_event(metadata={}).metadata == {}
    assert canonical_event_content(make_event(metadata=None)) != canonical_event_content(
        make_event(metadata={})
    )


def test_canonical_content_differs_by_event_version():
    assert canonical_event_content(make_event(event_version="1.0")) != canonical_event_content(
        make_event(event_version="1.1")
    )


def test_canonical_content_differs_by_payload():
    assert canonical_event_content(make_event(payload={"a": 1})) != canonical_event_content(
        make_event(payload={"a": 2})
    )


def test_canonical_content_differs_by_tenant_and_aggregate():
    base = canonical_event_content(make_event())
    assert base != canonical_event_content(make_event(tenant_id="tenant-2"))
    assert base != canonical_event_content(make_event(aggregate_id="exec-2"))
    assert base != canonical_event_content(make_event(event_type="PositionClosed"))
    assert base != canonical_event_content(make_event(sequence=2))


def test_occurred_at_normalized_to_utc():
    ist = datetime(2026, 6, 15, 16, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    utc = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert canonical_event_content(make_event(occurred_at=ist)) == canonical_event_content(
        make_event(occurred_at=utc)
    )


def test_canonical_content_is_utf8_safe_and_ascii_encoded():
    event = make_event(payload={"note": "naïve—üñí"})
    canonical = canonical_event_content(event)
    canonical.encode("ascii")  # ensure_ascii=True representation
    assert canonical == canonical_event_content(make_event(payload={"note": "naïve—üñí"}))
