"""Upstox adapter — Adapter #1 (Phase 6.5.0.2).

All Upstox-specific concepts (base URLs, OAuth, tokens, instrument keys,
transaction types, product codes, response formats, HTTP-status handling,
error strings, order status strings) live in this package and the raw
client in ``app.services.upstox``. The rest of the application consumes the
canonical :class:`BrokerAdapter` contract through the gateway.
"""

from app.brokers.adapters.upstox.adapter import UpstoxAdapter
from app.brokers.adapters.upstox.mapper import UPSTOX_INSTRUMENT_KEYS

__all__ = ["UPSTOX_INSTRUMENT_KEYS", "UpstoxAdapter"]
