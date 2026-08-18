"""Broker gateway (Phase 6.5.0.2).

Application services obtain broker adapters ONLY through this gateway (or
the registry it wraps) — broker selection happens in ONE controlled
location, never scattered as ``if broker == "UPSTOX"`` checks across
services. The gateway is broker-agnostic: a second adapter registered in
the registry becomes reachable without changing strategy, risk, capital,
portfolio, Exit Intent or paper-trading code.
"""

from __future__ import annotations

from typing import Any

from app.brokers.domain.models import BrokerConnectionContext
from app.brokers.registry import BrokerRegistry, BROKER_REGISTRY


class BrokerGateway:
    """The application's single entry point for broker adapters."""

    def __init__(self, registry: BrokerRegistry | None = None):
        self._registry = registry if registry is not None else BROKER_REGISTRY

    @property
    def registry(self) -> BrokerRegistry:
        return self._registry

    def create(self, broker_id, **kwargs: Any):
        """Create an adapter for ``broker_id`` (deterministic; unknown
        brokers raise BrokerError(BROKER_UNKNOWN))."""
        return self._registry.create(broker_id, **kwargs)

    def for_connection(self, connection: BrokerConnectionContext, **kwargs: Any):
        """Create the adapter for a user's broker connection.

        ``connection.broker`` selects the adapter; the connection context is
        attached to the adapter so user/account scope travels with every
        call. The current single-user MVP may pass the access token via
        ``kwargs``; the future persistent connection model resolves the
        credential from the connection itself.
        """
        adapter = self._registry.create(connection.broker, **kwargs)
        if hasattr(adapter, "_connection_context") and getattr(adapter, "_connection_context") is None:
            adapter._connection_context = connection
        return adapter

    def default(self, **kwargs: Any):
        """Return the adapter when EXACTLY ONE broker is registered.

        Convenience for the current single-broker MVP. Raises
        BrokerError(BROKER_UNKNOWN) when zero or multiple brokers are
        registered — a caller must then select explicitly via ``create`` /
        ``for_connection``.
        """
        known = self._registry.known_brokers()
        if len(known) != 1:
            raise self._unknown_default(len(known))
        return self._registry.create(known[0], **kwargs)

    @staticmethod
    def _unknown_default(count: int):
        from app.brokers.domain.errors import BrokerError, BrokerErrorCode

        if count == 0:
            return BrokerError(BrokerErrorCode.BROKER_UNKNOWN, "No broker adapters are registered.")
        return BrokerError(
            BrokerErrorCode.BROKER_UNKNOWN,
            f"{count} brokers are registered — broker selection must be explicit.",
        )


# Module-level singleton — the app's one gateway.
gateway = BrokerGateway()
