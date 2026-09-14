"""FYERS adapter — Adapter #2 (broker-neutral contract).

All FYERS-specific concepts (base URLs, OAuth generate-authcode /
validate-authcode, appIdHash, tokens, FYERS symbol grammar, short-field
payloads, order status codes, error strings) live in this package and
the raw client in ``app.services.fyers``. The rest of the application
consumes the canonical :class:`BrokerAdapter` contract through the
gateway. Customer identity (the FYERS Login ID) is extracted ONLY via
``app.brokers.adapters.fyers.profile`` — the API App ID is never an
ownership identity.
"""

from app.brokers.adapters.fyers.adapter import FyersAdapter
from app.brokers.adapters.fyers.mapper import FYERS_INSTRUMENTS

__all__ = ["FYERS_INSTRUMENTS", "FyersAdapter"]
