"""Day 37 — Domain Event Foundation publisher abstraction.

Defines the EventPublisher protocol that domain producers depend on.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import DomainEvent


@runtime_checkable
class EventPublisher(Protocol):
    """Abstraction for publishing domain events.

    Domain producers should depend on this protocol rather than
    the concrete event bus to maintain loose coupling and allow
    for different implementations (e.g., in-process, distributed).
    """

    def publish(self, event: DomainEvent) -> None:
        """Publish a domain event.

        Args:
            event: The domain event to publish.

        Returns:
            None.

        Note:
            Implementations must ensure that the event is delivered
            to all registered handlers for the event's type.
        """
        ...