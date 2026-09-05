"""Day 37 — Domain Event Foundation public API.

Exports the core components of the domain event system:
- DomainEvent: immutable event envelope
- EventPublisher: abstraction for publishing events
- DomainEventHandler: abstraction for handling events
- EventBus: in-process implementation of EventPublisher
- HandlerScopedIdempotency: process-local idempotency mechanism
"""

from .contracts import DomainEvent
from .bus import EventBus
from .handler import DomainEventHandler
from .idempotency import HandlerScopedIdempotency
from .publisher import EventPublisher

__all__ = [
    "DomainEvent",
    "EventPublisher",
    "DomainEventHandler",
    "EventBus",
    "HandlerScopedIdempotency",
]