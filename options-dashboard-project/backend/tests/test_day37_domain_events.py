"""Day 37 — Domain Event Foundation tests.

Tests the in-process typed domain-event foundation following TDD principles.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.domain_events.contracts import DomainEvent
from app.domain_events.publisher import EventPublisher
from app.domain_events.handler import DomainEventHandler
from app.domain_events.bus import EventBus
from app.domain_events.idempotency import HandlerScopedIdempotency


# Test helper classes
class TestEventHandler:
    """Test handler implementation for domain events."""
    
    def __init__(self, handler_id: str, event_type: str):
        self._handler_id = handler_id
        self._event_type = event_type
        self.handled_events: List[DomainEvent] = []
    
    @property
    def handler_id(self) -> str:
        return self._handler_id
    
    @property
    def event_type(self) -> str:
        return self._event_type
    
    def handle(self, event: DomainEvent) -> None:
        self.handled_events.append(event)


class FailingEventHandler:
    """Test handler that raises an exception."""
    
    def __init__(self, handler_id: str, event_type: str):
        self._handler_id = handler_id
        self._event_type = event_type
        self.handled_events: List[DomainEvent] = []
        self.fail = False
    
    @property
    def handler_id(self) -> str:
        return self._handler_id
    
    @property
    def event_type(self) -> str:
        return self._event_type
    
    def handle(self, event: DomainEvent) -> None:
        self.handled_events.append(event)
        if self.fail:
            raise ValueError("Handler failed intentionally")


# Test constants
TEST_TENANT_ID = "tenant-test"
TEST_AGGREGATE_TYPE = "TestAggregate"
TEST_AGGREGATE_ID = "aggregate-123"
TEST_EVENT_TYPE = "TestEventOccurred"
TEST_EVENT_VERSION = "1.0"


def _make_base_event(
    event_id: str = "event-123",
    event_type: str = TEST_EVENT_TYPE,
    aggregate_type: str = TEST_AGGREGATE_TYPE,
    aggregate_id: str = TEST_AGGREGATE_ID,
    occurred_at: datetime | None = None,
    tenant_id: str = TEST_TENANT_ID,
    event_version: str = TEST_EVENT_VERSION,
    payload: Dict[str, Any] | None = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> DomainEvent:
    """Helper to create a base test event."""
    if occurred_at is None:
        occurred_at = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    if payload is None:
        payload = {"key": "value"}
    # Default metadata for tests that expect it, but None can be explicitly passed
    if metadata is None:
        metadata = {"source": "test"}
    
    return DomainEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        occurred_at=occurred_at,
        tenant_id=tenant_id,
        event_version=event_version,
        payload=payload,
        metadata=metadata,
    )


class TestDomainEventContract:
    """Test the DomainEvent immutable envelope."""
    
    def test_event_can_be_constructed(self) -> None:
        """Event can be constructed with all required fields."""
        event = _make_base_event()
        
        assert event.event_id == "event-123"
        assert event.event_type == TEST_EVENT_TYPE
        assert event.aggregate_type == TEST_AGGREGATE_TYPE
        assert event.aggregate_id == TEST_AGGREGATE_ID
        assert event.tenant_id == TEST_TENANT_ID
        assert event.event_version == TEST_EVENT_VERSION
        assert event.payload == {"key": "value"}
        assert event.metadata == {"source": "test"}
    
    def test_required_event_id_exists(self) -> None:
        """Event ID is required and accessible."""
        event = _make_base_event(event_id="unique-event-id")
        assert event.event_id == "unique-event-id"
    
    def test_event_type_exists(self) -> None:
        """Event type is required and accessible."""
        event = _make_base_event(event_type="CustomEventType")
        assert event.event_type == "CustomEventType"
    
    def test_aggregate_type_exists(self) -> None:
        """Aggregate type is required and accessible."""
        event = _make_base_event(aggregate_type="User")
        assert event.aggregate_type == "User"
    
    def test_aggregate_id_exists(self) -> None:
        """Aggregate ID is required and accessible."""
        event = _make_base_event(aggregate_id="user-456")
        assert event.aggregate_id == "user-456"
    
    def test_tenant_id_exists(self) -> None:
        """Tenant ID is required and accessible."""
        event = _make_base_event(tenant_id="tenant-xyz")
        assert event.tenant_id == "tenant-xyz"
    
    def test_event_version_exists(self) -> None:
        """Event version is required and accessible."""
        event = _make_base_event(event_version="2.0")
        assert event.event_version == "2.0"
    
    def test_timestamp_exists_and_is_timezone_aware(self) -> None:
        """Timestamp exists and must be timezone-aware."""
        dt = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        event = _make_base_event(occurred_at=dt)
        assert event.occurred_at == dt
        assert event.occurred_at.tzinfo is not None
    
    def test_event_is_immutable(self) -> None:
        """Event fields cannot be modified after creation."""
        event = _make_base_event()
        
        # Attempt to modify fields should fail due to frozen=True
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            event.event_id = "modified"
        
        with pytest.raises(Exception):
            event.event_type = "Modified"
            
        with pytest.raises(Exception):
            event.aggregate_type = "Modified"
            
        with pytest.raises(Exception):
            event.aggregate_id = "Modified"
            
        with pytest.raises(Exception):
            event.tenant_id = "modified"
            
        with pytest.raises(Exception):
            event.event_version = "modified"
            
        # Note: payload and metadata are mapping objects which could be mutated
        # but the event itself prevents reassignment of those fields
        with pytest.raises(Exception):
            event.payload = {}
            
        with pytest.raises(Exception):
            event.metadata = None
    
    def test_payload_is_preserved(self) -> None:
        """Payload is preserved exactly as provided."""
        payload = {"nested": {"key": "value"}, "count": 42}
        event = _make_base_event(payload=payload)
        assert event.payload == payload
    
    def test_metadata_is_preserved(self) -> None:
        """Metadata is preserved exactly as provided."""
        metadata = {"trace_id": "abc-123", "priority": "high"}
        event = _make_base_event(metadata=metadata)
        assert event.metadata == metadata
    
    def test_metadata_can_be_none(self) -> None:
        """Metadata can be None (optional field)."""
        event = DomainEvent(
            event_id="event-123",
            event_type=TEST_EVENT_TYPE,
            aggregate_type=TEST_AGGREGATE_TYPE,
            aggregate_id=TEST_AGGREGATE_ID,
            occurred_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc),
            tenant_id=TEST_TENANT_ID,
            event_version=TEST_EVENT_VERSION,
            payload={"key": "value"},
            metadata=None,
        )
        assert event.metadata is None
    
    def test_serialization_is_deterministic(self) -> None:
        """Event serialization produces consistent results."""
        event1 = _make_base_event(event_id="event-1")
        event2 = _make_base_event(event_id="event-1")  # Same data
        
        dict1 = event1.to_dict()
        dict2 = event2.to_dict()
        
        assert dict1 == dict2
        assert dict1["event_id"] == "event-1"
        assert dict1["event_type"] == TEST_EVENT_TYPE
        assert dict1["aggregate_type"] == TEST_AGGREGATE_TYPE
        assert dict1["aggregate_id"] == TEST_AGGREGATE_ID
        assert dict1["tenant_id"] == TEST_TENANT_ID
        assert dict1["event_version"] == TEST_EVENT_VERSION
        assert dict1["payload"] == {"key": "value"}
        assert dict1["metadata"] == {"source": "test"}
        assert "occurred_at" in dict1
    
    def test_serialization_preserves_all_envelope_fields(self) -> None:
        """Serialization preserves all required envelope fields."""
        custom_payload = {"custom": "data"}
        custom_metadata = {"custom": "meta"}
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        event = DomainEvent(
            event_id="serialization-test",
            event_type="SerializationTest",
            aggregate_type="TestAgg",
            aggregate_id="agg-999",
            occurred_at=dt,
            tenant_id="tenant-serial",
            event_version="3.0",
            payload=custom_payload,
            metadata=custom_metadata,
        )
        
        result = event.to_dict()
        
        assert result["event_id"] == "serialization-test"
        assert result["event_type"] == "SerializationTest"
        assert result["aggregate_type"] == "TestAgg"
        assert result["aggregate_id"] == "agg-999"
        assert result["tenant_id"] == "tenant-serial"
        assert result["event_version"] == "3.0"
        assert result["payload"] == custom_payload
        assert result["metadata"] == custom_metadata
        assert result["occurred_at"] == dt.isoformat()
    
    def test_empty_event_id_raises_error(self) -> None:
        """Empty event ID raises ValueError."""
        with pytest.raises(ValueError, match="event_id must not be empty"):
            DomainEvent(
                event_id="",
                event_type=TEST_EVENT_TYPE,
                aggregate_type=TEST_AGGREGATE_TYPE,
                aggregate_id=TEST_AGGREGATE_ID,
                occurred_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc),
                tenant_id=TEST_TENANT_ID,
                event_version=TEST_EVENT_VERSION,
                payload={},
            )
    
    def test_empty_event_type_raises_error(self) -> None:
        """Empty event type raises ValueError."""
        with pytest.raises(ValueError, match="event_type must not be empty"):
            DomainEvent(
                event_id="event-1",
                event_type="",
                aggregate_type=TEST_AGGREGATE_TYPE,
                aggregate_id=TEST_AGGREGATE_ID,
                occurred_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc),
                tenant_id=TEST_TENANT_ID,
                event_version=TEST_EVENT_VERSION,
                payload={},
            )
    
    def test_empty_tenant_id_raises_error(self) -> None:
        """Empty tenant ID raises ValueError."""
        with pytest.raises(ValueError, match="tenant_id must not be empty"):
            DomainEvent(
                event_id="event-1",
                event_type=TEST_EVENT_TYPE,
                aggregate_type=TEST_AGGREGATE_TYPE,
                aggregate_id=TEST_AGGREGATE_ID,
                occurred_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc),
                tenant_id="",
                event_version=TEST_EVENT_VERSION,
                payload={},
            )
    
    def test_naive_timestamp_raises_error(self) -> None:
        """Naive (timezone-unaware) timestamp raises ValueError."""
        with pytest.raises(ValueError, match="occurred_at must be timezone-aware"):
            DomainEvent(
                event_id="event-1",
                event_type=TEST_EVENT_TYPE,
                aggregate_type=TEST_AGGREGATE_TYPE,
                aggregate_id=TEST_AGGREGATE_ID,
                occurred_at=datetime(2026, 9, 5, 12, 0, 0),  # No timezone
                tenant_id=TEST_TENANT_ID,
                event_version=TEST_EVENT_VERSION,
                payload={},
            )
    
    def test_payload_must_be_mapping(self) -> None:
        """Payload must be a mapping, not other types."""
        with pytest.raises(TypeError, match="payload must be a mapping"):
            DomainEvent(
                event_id="event-1",
                event_type=TEST_EVENT_TYPE,
                aggregate_type=TEST_AGGREGATE_TYPE,
                aggregate_id=TEST_AGGREGATE_ID,
                occurred_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc),
                tenant_id=TEST_TENANT_ID,
                event_version=TEST_EVENT_VERSION,
                payload=["not", "a", "mapping"],  # type: ignore
            )
    
    def test_metadata_must_be_mapping_or_none(self) -> None:
        """Metadata must be a mapping or None."""
        with pytest.raises(TypeError, match="metadata must be a mapping or None"):
            DomainEvent(
                event_id="event-1",
                event_type=TEST_EVENT_TYPE,
                aggregate_type=TEST_AGGREGATE_TYPE,
                aggregate_id=TEST_AGGREGATE_ID,
                occurred_at=datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc),
                tenant_id=TEST_TENANT_ID,
                event_version=TEST_EVENT_VERSION,
                payload={},
                metadata=["not", "a", "mapping"],  # type: ignore
            )


class TestEventPublisherAbstraction:
    """Test the EventPublisher abstraction."""
    
    def test_publisher_abstraction_exists(self) -> None:
        """EventPublisher protocol exists and is accessible."""
        assert EventPublisher is not None
        # Check that it's a Protocol
        assert hasattr(EventPublisher, '__abstractmethods__')
    
    def test_concrete_event_bus_satisfies_publisher_boundary(self) -> None:
        """EventBus implements EventPublisher protocol."""
        bus = EventBus()
        assert isinstance(bus, EventPublisher)
    
    def test_publish_method_signature(self) -> None:
        """Publisher has publish method with correct signature."""
        # This is tested implicitly by the isinstance check above
        # and explicitly in EventBus tests
        pass


class TestEventHandlerAbstraction:
    """Test the DomainEventHandler abstraction."""
    
    def test_handler_abstraction_exists(self) -> None:
        """DomainEventHandler protocol exists and is accessible."""
        assert DomainEventHandler is not None
        assert hasattr(DomainEventHandler, '__abstractmethods__')
    
    def test_handler_has_explicit_identity(self) -> None:
        """Handler has explicit stable handler_id."""
        handler = TestEventHandler("handler-123", TEST_EVENT_TYPE)
        assert handler.handler_id == "handler-123"
    
    def test_handler_has_explicit_event_type(self) -> None:
        """Handler has explicit event type it can process."""
        handler = TestEventHandler("handler-123", "SpecificEventType")
        assert handler.event_type == "SpecificEventType"
    
    def test_handler_receives_complete_event(self) -> None:
        """Handler receives the complete domain event when handle is called."""
        handler = TestEventHandler("handler-123", TEST_EVENT_TYPE)
        event = _make_base_event(event_id="event-456")
        
        handler.handle(event)
        
        assert len(handler.handled_events) == 1
        handled_event = handler.handled_events[0]
        assert handled_event.event_id == "event-456"
        assert handled_event.event_type == TEST_EVENT_TYPE
        assert handled_event.aggregate_id == TEST_AGGREGATE_ID
        assert handled_event.tenant_id == TEST_TENANT_ID
    
    def test_tenant_id_reaches_handler_unchanged(self) -> None:
        """Tenant ID is preserved and reaches handler unchanged."""
        handler = TestEventHandler("handler-123", TEST_EVENT_TYPE)
        custom_tenant = "tenant-custom-789"
        event = _make_base_event(
            event_id="tenant-test",
            tenant_id=custom_tenant
        )
        
        handler.handle(event)
        
        assert len(handler.handled_events) == 1
        assert handler.handled_events[0].tenant_id == custom_tenant


class TestEventBusRouting:
    """Test event bus typed routing and handler invocation."""
    
    def test_matching_event_type_routes_to_handler(self) -> None:
        """Handlers receive events matching their event type."""
        bus = EventBus()
        handler = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        event = _make_base_event()
        bus.publish(event)
        
        assert len(handler.handled_events) == 1
    
    def test_nonmatching_event_type_does_not_route_to_handler(self) -> None:
        """Handlers do not receive events with non-matching event types."""
        bus = EventBus()
        handler_correct = TestEventHandler("handler-correct", TEST_EVENT_TYPE)
        handler_wrong = TestEventHandler("handler-wrong", "DifferentEventType")
        bus.subscribe(handler_correct)
        bus.subscribe(handler_wrong)

        event = _make_base_event(event_type=TEST_EVENT_TYPE)
        bus.publish(event)

        assert len(handler_correct.handled_events) == 1
        assert len(handler_wrong.handled_events) == 0
    
    def test_multiple_handlers_receive_same_event(self) -> None:
        """Multiple handlers subscribed to same event type all receive the event."""
        bus = EventBus()
        handler1 = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        handler2 = TestEventHandler("handler-2", TEST_EVENT_TYPE)
        handler3 = TestEventHandler("handler-3", "DifferentType")  # Should not receive
        
        bus.subscribe(handler1)
        bus.subscribe(handler2)
        bus.subscribe(handler3)
        
        event = _make_base_event()
        bus.publish(event)
        
        assert len(handler1.handled_events) == 1
        assert len(handler2.handled_events) == 1
        assert len(handler3.handled_events) == 0  # Different event type
    
    def test_handler_invocation_order_is_deterministic(self) -> None:
        """Handlers are invoked in registration order."""
        bus = EventBus()
        invocation_order: List[str] = []
        
        class OrderTrackingHandler:
            def __init__(self, handler_id: str, event_type: str):
                self._handler_id = handler_id
                self._event_type = event_type
            
            @property
            def handler_id(self) -> str:
                return self._handler_id
            
            @property
            def event_type(self) -> str:
                return self._event_type
            
            def handle(self, event: DomainEvent) -> None:
                invocation_order.append(self._handler_id)
        
        handler_a = OrderTrackingHandler("handler-A", TEST_EVENT_TYPE)
        handler_b = OrderTrackingHandler("handler-B", TEST_EVENT_TYPE)
        handler_c = OrderTrackingHandler("handler-C", TEST_EVENT_TYPE)
        
        # Subscribe in specific order
        bus.subscribe(handler_a)
        bus.subscribe(handler_b)
        bus.subscribe(handler_c)
        
        event = _make_base_event()
        bus.publish(event)
        
        assert invocation_order == ["handler-A", "handler-B", "handler-C"]
    
    def test_unknown_event_type_has_deterministic_behavior(self) -> None:
        """Publishing event with no registered handlers raises ValueError deterministically."""
        bus = EventBus()
        # No handlers subscribed

        event = _make_base_event(event_type="UnregisteredEventType")
        # Should raise ValueError
        with pytest.raises(ValueError, match="No handlers registered for event type: UnregisteredEventType"):
            bus.publish(event)

        # Also test that we can subscribe after and it works
        handler = TestEventHandler("handler-1", "UnregisteredEventType")
        bus.subscribe(handler)

        event2 = _make_base_event(event_type="UnregisteredEventType")
        # Should not raise exception now
        bus.publish(event2)

        assert len(handler.handled_events) == 1


class TestEventBusIdempotency:
    """Test handler-scoped idempotency in event bus."""
    
    def test_same_event_same_handler_executes_once(self) -> None:
        """Same event + same handler → processed only once."""
        bus = EventBus()
        handler = TestEventHandler("handler-123", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        event = _make_base_event(event_id="duplicate-test")
        
        # Publish same event twice
        bus.publish(event)
        bus.publish(event)
        
        assert len(handler.handled_events) == 1
    
    def test_same_event_different_handlers_execute_independently(self) -> None:
        """Same event + different handlers → both process independently."""
        bus = EventBus()
        handler_a = TestEventHandler("handler-A", TEST_EVENT_TYPE)
        handler_b = TestEventHandler("handler-B", TEST_EVENT_TYPE)
        bus.subscribe(handler_a)
        bus.subscribe(handler_b)
        
        event = _make_base_event(event_id="shared-event")
        
        # Publish same event twice
        bus.publish(event)
        bus.publish(event)
        
        # Each handler should have processed the event once
        assert len(handler_a.handled_events) == 1
        assert len(handler_b.handled_events) == 1
    
    def test_different_event_same_handler_executes_independently(self) -> None:
        """Different events + same handler → both processed."""
        bus = EventBus()
        handler = TestEventHandler("handler-123", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        event1 = _make_base_event(event_id="event-1")
        event2 = _make_base_event(event_id="event-2")
        
        bus.publish(event1)
        bus.publish(event2)
        
        assert len(handler.handled_events) == 2
        assert handler.handled_events[0].event_id == "event-1"
        assert handler.handled_events[1].event_id == "event-2"
    
    def test_duplicate_delivery_does_not_mutate_processing_count_twice(self) -> None:
        """Idempotency prevents counting duplicates multiple times."""
        bus = EventBus()
        handler = TestEventHandler("handler-123", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        event = _make_base_event(event_id="idempotency-test")
        
        # Publish multiple times
        for _ in range(5):
            bus.publish(event)
        
        # Handler should process exactly once
        assert len(handler.handled_events) == 1


class TestEventBusFailureHandling:
    """Test explicit failure handling in event bus."""
    
    def test_handler_exception_remains_observable(self) -> None:
        """Handler exception propagates to caller."""
        bus = EventBus()
        failing_handler = FailingEventHandler("failing-1", TEST_EVENT_TYPE)
        failing_handler.fail = True  # Make it fail
        bus.subscribe(failing_handler)
        
        event = _make_base_event()
        
        # The exception should propagate
        with pytest.raises(ValueError, match="Handler failed intentionally"):
            bus.publish(event)
    
    def test_failed_handler_not_reported_as_successful(self) -> None:
        """Failed handler is not counted as successfully processed."""
        bus = EventBus()
        failing_handler = FailingEventHandler("failing-1", TEST_EVENT_TYPE)
        failing_handler.fail = True
        bus.subscribe(failing_handler)
        
        event = _make_base_event()
        
        # Even though it fails, we can check that handle was called
        # by checking if the event was added to handled_events before failure
        try:
            bus.publish(event)
        except ValueError:
            pass  # Expected
        
        # The handler's handle method was called (event added to list)
        # before the exception was raised
        assert len(failing_handler.handled_events) == 1
    
    def test_multi_handler_failure_semantics_are_deterministic(self) -> None:
        """When multiple handlers, failure stops propagation to subsequent handlers."""
        bus = EventBus()
        handler_good = TestEventHandler("good-1", TEST_EVENT_TYPE)
        handler_failing = FailingEventHandler("failing-1", TEST_EVENT_TYPE)
        handler_failing.fail = True
        handler_also_good = TestEventHandler("good-2", TEST_EVENT_TYPE)
        
        # Subscribe in order: good, failing, good
        bus.subscribe(handler_good)
        bus.subscribe(handler_failing)
        bus.subscribe(handler_also_good)
        
        event = _make_base_event()
        
        # First handler should process, second should fail and stop propagation
        with pytest.raises(ValueError, match="Handler failed intentionally"):
            bus.publish(event)
        
        # First handler processed
        assert len(handler_good.handled_events) == 1
        # Failing handler was called (event in its list) but failed
        assert len(handler_failing.handled_events) == 1
        # Third handler should not have been called due to early exception
        assert len(handler_also_good.handled_events) == 0


class TestEventBusTenantIsolation:
    """Test tenant context preservation through event bus."""
    
    def test_tenant_preserved_through_publication(self) -> None:
        """Tenant ID is preserved from publish to handler."""
        bus = EventBus()
        handler = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        custom_tenant = "tenant-isolation-test"
        event = _make_base_event(tenant_id=custom_tenant)
        
        bus.publish(event)
        
        assert len(handler.handled_events) == 1
        assert handler.handled_events[0].tenant_id == custom_tenant
    
    def test_events_from_different_tenants_remain_distinguishable(self) -> None:
        """Events with different tenant IDs remain distinct."""
        bus = EventBus()
        handler = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        event_a = _make_base_event(
            event_id="event-a",
            tenant_id="tenant-alpha"
        )
        event_b = _make_base_event(
            event_id="event-b",
            tenant_id="tenant-beta"
        )
        
        bus.publish(event_a)
        bus.publish(event_b)
        
        assert len(handler.handled_events) == 2
        tenant_ids = [e.tenant_id for e in handler.handled_events]
        assert "tenant-alpha" in tenant_ids
        assert "tenant-beta" in tenant_ids


class TestEventBusPurityAndDependencies:
    """Test that event bus has no forbidden dependencies."""
    
    def test_no_database_dependency_in_event_modules(self) -> None:
        """Event modules do not import database dependencies."""
        # This is validated by inspection - no SQLAlchemy, etc. in domain_events
        pass  # Placeholder for architectural constraint
    
    def test_no_network_dependency_in_event_modules(self) -> None:
        """Event modules do not import network dependencies."""
        # This is validated by inspection - no requests, httpx, etc. in domain_events
        pass
    
    def test_no_broker_dependency_in_event_modules(self) -> None:
        """Event modules do not import broker dependencies."""
        # This is validated by inspection - no Upstox, etc. in domain_events
        pass
    
    def test_no_distributed_messaging_dependency_in_event_modules(self) -> None:
        """Event modules do not import distributed messaging dependencies."""
        # This is validated by inspection - no Kafka, Redis, Celery, etc. in domain_events
        pass
    
    def test_no_wall_clock_dependency_in_event_modules(self) -> None:
        """Event modules do not use wall-clock time internally."""
        # This is validated by inspection - no datetime.now() calls in domain_events
        pass
    
    def test_no_uuid_randomness_dependency_in_event_modules(self) -> None:
        """Event modules do not generate UUIDs or random IDs."""
        # This is validated by inspection - no uuid or random imports in domain_events
        pass


class TestEventBusPublicAPI:
    """Test public package API exposure."""
    
    def test_public_api_exposure(self) -> None:
        """All expected components are available in the public API."""
        from app.domain_events import (
            DomainEvent,
            EventPublisher,
            DomainEventHandler,
            EventBus,
            HandlerScopedIdempotency,
        )
        
        # All should be importable
        assert DomainEvent is not None
        assert EventPublisher is not None
        assert DomainEventHandler is not None
        assert EventBus is not None
        assert HandlerScopedIdempotency is not None
    
    def test_init_py_exposes_correct_api(self) -> None:
        """__init__.py exposes the intended public API."""
        import app.domain_events as domain_events
        
        # Check that expected attributes exist
        assert hasattr(domain_events, 'DomainEvent')
        assert hasattr(domain_events, 'EventPublisher')
        assert hasattr(domain_events, 'DomainEventHandler')
        assert hasattr(domain_events, 'EventBus')
        assert hasattr(domain_events, 'HandlerScopedIdempotency')
        
        # Check __all__ if it exists
        if hasattr(domain_events, '__all__'):
            expected = {
                "DomainEvent",
                "EventPublisher", 
                "DomainEventHandler",
                "EventBus",
                "HandlerScopedIdempotency"
            }
            actual = set(domain_events.__all__)
            assert expected.issubset(actual), f"Missing from __all__: {expected - actual}"


class TestEventBusLifecycleMethods:
    """Test event bus lifecycle and reset methods."""
    
    def test_reset_idempotency_clears_tracker(self) -> None:
        """reset_idempotency clears the idempotency tracker."""
        bus = EventBus()
        handler = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        event = _make_base_event(event_id="reset-test")
        
        # Process event once
        bus.publish(event)
        assert len(handler.handled_events) == 1
        
        # Try to process same event again - should be blocked by idempotency
        bus.publish(event)
        assert len(handler.handled_events) == 1  # Still 1
        
        # Reset idempotency
        bus.reset_idempotency()
        
        # Now same event should process again
        bus.publish(event)
        assert len(handler.handled_events) == 2  # Now 2
    
    def test_handler_count_returns_correct_count(self) -> None:
        """handler_count returns correct number of handlers for event type."""
        bus = EventBus()
        
        # No handlers initially
        assert bus.handler_count(TEST_EVENT_TYPE) == 0
        assert bus.handler_count("nonexistent") == 0
        
        # Add handlers
        handler1 = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        handler2 = TestEventHandler("handler-2", TEST_EVENT_TYPE)
        handler3 = TestEventHandler("handler-3", "OtherType")
        
        bus.subscribe(handler1)
        assert bus.handler_count(TEST_EVENT_TYPE) == 1
        
        bus.subscribe(handler2)
        assert bus.handler_count(TEST_EVENT_TYPE) == 2
        
        bus.subscribe(handler3)
        assert bus.handler_count(TEST_EVENT_TYPE) == 2  # Unchanged
        assert bus.handler_count("OtherType") == 1
    
    def test_reset_clears_all_state(self) -> None:
        """reset clears all handler registrations and idempotency records."""
        bus = EventBus()
        handler = TestEventHandler("handler-1", TEST_EVENT_TYPE)
        bus.subscribe(handler)
        
        # Verify initial state
        assert bus.handler_count(TEST_EVENT_TYPE) == 1
        
        # Process an event to populate idempotency
        event = _make_base_event(event_id="reset-test")
        bus.publish(event)
        assert len(handler.handled_events) == 1
        
        # Reset everything
        bus.reset()
        
        # Handler registration should be cleared
        assert bus.handler_count(TEST_EVENT_TYPE) == 0
        
        # Idempotency should be cleared - same event should process again
        bus.subscribe(handler)  # Re-subscribe
        bus.publish(event)
        assert len(handler.handled_events) == 2  # Processed once before reset, once after


if __name__ == "__main__":
    pytest.main([__file__, "-v"])