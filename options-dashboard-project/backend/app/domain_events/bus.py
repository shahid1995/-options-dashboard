"""Day 37 — Domain Event Foundation in-process event bus.

Implements an in-process event bus that satisfies the EventPublisher abstraction.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple
from .contracts import DomainEvent
from .handler import DomainEventHandler
from .idempotency import HandlerScopedIdempotency
from .publisher import EventPublisher


class EventBus(EventPublisher):
    """In-process event bus for domain events.

    Provides typed routing, deterministic handler ordering,
    handler-scoped idempotency, and explicit failure handling.

    The bus maintains:
    - Handler registry indexed by event type
    - Registration order preservation for deterministic invocation
    - Idempotency tracking to prevent duplicate handling
    """

    def __init__(self) -> None:
        """Initialize the event bus."""
        # Map event type -> list of handlers in registration order
        self._handlers: Dict[str, List[DomainEventHandler]] = defaultdict(list)
        self._idempotency = HandlerScopedIdempotency()

    def subscribe(self, handler: DomainEventHandler) -> None:
        """Subscribe a handler to its event type.

        Args:
            handler: The handler to subscribe. Must implement DomainEventHandler.

        Note:
            Handlers are invoked in registration order for deterministic behavior.
            A handler can only be subscribed once to prevent accidental duplicates.
        """
        event_type = handler.event_type
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        """Publish a domain event to all registered handlers.

        Args:
            event: The domain event to publish.

        Behavior:
            - Looks up handlers registered for event.event_type
            - Invokes each handler in registration order
            - Applies handler-scoped idempotency (event_id, handler_id)
            - Propagates any handler exceptions to the caller
            - Events with no registered handlers raise a ValueError deterministically

        Raises:
            Exception: If any handler raises an exception, it is propagated
                      immediately and subsequent handlers are not invoked.
        """
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            raise ValueError(f"No handlers registered for event type: {event.event_type}")

        for handler in handlers:
            # Check idempotency before processing
            if self._idempotency.is_duplicate(event, handler):
                # Skip duplicate delivery to same handler
                continue

            # Mark as processed before invocation to handle reentrant cases
            self._idempotency.mark_processed(event, handler)

            # Invoke handler - any exception will propagate to caller
            handler.handle(event)

    def reset_idempotency(self) -> None:
        """Reset the idempotency tracker.

        Primarily useful for testing to isolate test runs.
        """
        self._idempotency.reset()

    def handler_count(self, event_type: str) -> int:
        """Get the number of handlers registered for an event type.

        Args:
            event_type: The event type to check.

        Returns:
            Number of handlers registered for the given event type.
        """
        return len(self._handlers.get(event_type, []))

    def reset(self) -> None:
        """Reset the entire event bus state.

        Clears all handler registrations and idempotency records.
        Primarily useful for testing.
        """
        self._handlers.clear()
        self._idempotency.reset()