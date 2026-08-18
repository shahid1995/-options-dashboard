"""Broker registry (Phase 6.5.0.2).

One controlled place where broker IDs resolve to adapter classes. Registering
an adapter is what makes a broker reachable — the future Zerodha / Dhan /
Angel One / Fyers adapters become a one-line registration here. Unknown
brokers fail safely with ``BrokerError(BROKER_UNKNOWN)``; selection is
deterministic (dictionary order, no probing).
"""

from __future__ import annotations

from typing import Any

from app.brokers.domain.errors import BrokerError, BrokerErrorCode


def _broker_key(broker_id) -> str:
    """Normalize a broker id (enum member, enum value, or plain string) to
    its canonical uppercase key. Enum members on Python < 3.11 stringify as
    ``BrokerId.UPSTOX``, so always use ``.value`` when available."""
    value = getattr(broker_id, "value", broker_id)
    return str(value).upper()


class BrokerRegistry:
    """Maps BrokerId values → adapter factory (class or callable)."""

    def __init__(self) -> None:
        self._factories: dict[str, type] = {}

    def register(self, broker_id, factory: type) -> None:
        """Register an adapter factory under a broker id (idempotent)."""
        key = _broker_key(broker_id)
        if key in self._factories:
            return  # idempotent — later registrations do not clobber
        self._factories[key] = factory

    def get(self, broker_id) -> type:
        """Resolve the adapter factory for a broker id.

        Raises BrokerError(BROKER_UNKNOWN) for unregistered brokers — never
        guesses, never falls back to a default broker silently.
        """
        key = _broker_key(broker_id)
        factory = self._factories.get(key)
        if factory is None:
            raise BrokerError(
                BrokerErrorCode.BROKER_UNKNOWN,
                f"No adapter is registered for broker '{key}'.",
            )
        return factory

    def create(self, broker_id, **kwargs: Any):
        """Instantiate the adapter for a broker id (deterministic)."""
        factory = self.get(broker_id)
        return factory(**kwargs)

    def known_brokers(self) -> tuple[str, ...]:
        return tuple(self._factories)

    def __contains__(self, broker_id) -> bool:
        return _broker_key(broker_id) in self._factories

    def __len__(self) -> int:
        return len(self._factories)


BROKER_REGISTRY = BrokerRegistry()


def register_default_brokers() -> None:
    """Register the platform's adapter set (idempotent, safe to call twice).

    Phase 6.5.0.2 ships exactly one adapter (Upstox). Future brokers add
    their registration here — application services never change.
    """
    from app.brokers.adapters.upstox.adapter import UpstoxAdapter
    from app.brokers.domain.enums import BROKER_ID_UPSTOX

    BROKER_REGISTRY.register(BROKER_ID_UPSTOX, UpstoxAdapter)


register_default_brokers()
