"""Day 37 — Domain Event Foundation handler abstraction.

Defines the DomainEventHandler protocol that event handlers must implement.
"""

from __future__ import annotations

from typing import Protocol

from .contracts import DomainEvent


class DomainEventHandler(Protocol):
    """Protocol for domain event handlers.

    Each handler must have an explicit stable identity and declare
    which event types it can handle.
    """

    @property
    def handler_id(self) -> str:
        """Stable identifier for this handler instance.

        Used for idempotency and diagnostics. Must be unique per handler
        instance within the application.

        Returns:
            A string uniquely identifying this handler.
        """
        ...

    @property
    def event_type(self) -> str:
        """The event type this handler can process.

        Returns:
            The event type string that this handler subscribes to.
        """
        ...

    def handle(self, event: DomainEvent) -> None:
        """Process a domain event.

        Args:
            event: The domain event to handle.

        Returns:
            None.

        Raises:
            Exception: Any exception raised during handling will be
                      propagated to the event bus caller.
        """
        ...