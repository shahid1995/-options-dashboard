"""Day 37 — Domain Event Foundation idempotency mechanism.

Provides process-local handler-scoped idempotency for domain event handling.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple
from .contracts import DomainEvent
from .handler import DomainEventHandler


class HandlerScopedIdempotency:
    """Process-local idempotency tracker for domain event handlers.

    Idempotency key is (event_id, handler_id) ensuring:
    - Same event + same handler → processed only once
    - Same event + different handler → processed independently
    - Different event + same handler → processed independently

    This is in-process only and does not survive application restarts.
    """

    def __init__(self) -> None:
        """Initialize the idempotency tracker."""
        self._processed: Set[Tuple[str, str]] = set()

    def is_duplicate(self, event: DomainEvent, handler: DomainEventHandler) -> bool:
        """Check if this event has already been processed by this handler.

        Args:
            event: The domain event to check.
            handler: The handler that would process the event.

        Returns:
            True if the (event_id, handler_id) combination has been seen before,
            False otherwise.
        """
        key = (event.event_id, handler.handler_id)
        return key in self._processed

    def mark_processed(self, event: DomainEvent, handler: DomainEventHandler) -> None:
        """Mark an event as processed by a handler.

        Args:
            event: The domain event that was processed.
            handler: The handler that processed the event.
        """
        key = (event.event_id, handler.handler_id)
        self._processed.add(key)

    def reset(self) -> None:
        """Reset the idempotency tracker.

        Clears all recorded processed events. Primarily useful for testing.
        """
        self._processed.clear()