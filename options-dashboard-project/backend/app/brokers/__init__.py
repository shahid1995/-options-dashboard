"""Broker-neutral connectivity layer (Phase 6.5.0.2).

    Application
        ↓
    BrokerGateway  (app.brokers.gateway)
        ↓
    BrokerAdapter (app.brokers.domain.protocols)
        ├── UpstoxAdapter (app.brokers.adapters.upstox)
        └── future brokers (later milestones)

Domain contracts live in ``app.brokers.domain``; broker-specific concepts
live in ``app.brokers.adapters.<broker>`` and never leak upward.
"""

from app.brokers.domain.capabilities import BrokerCapabilities, BrokerCapability, CapabilityState
from app.brokers.domain.enums import (
    BROKER_ID_UPSTOX,
    BrokerId,
    ExecutionPolicy,
    InstrumentType,
    OptionType,
    OrderStatus,
    OrderType,
    Product,
    Segment,
    Side,
    Validity,
)
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.brokers.domain.models import (
    BrokerConnectionContext,
    BrokerInstrumentMapping,
    BrokerOrderRequest,
    BrokerOrderResult,
    InstrumentIdentity,
)
from app.brokers.domain.protocols import BrokerAdapter
from app.brokers.gateway import BrokerGateway, gateway
from app.brokers.registry import BrokerRegistry, BROKER_REGISTRY

__all__ = [
    "BROKER_ID_UPSTOX",
    "BROKER_REGISTRY",
    "BrokerAdapter",
    "BrokerCapabilities",
    "BrokerCapability",
    "BrokerConnectionContext",
    "BrokerError",
    "BrokerErrorCode",
    "BrokerGateway",
    "BrokerId",
    "BrokerInstrumentMapping",
    "BrokerOrderRequest",
    "BrokerOrderResult",
    "BrokerRegistry",
    "CapabilityState",
    "ExecutionPolicy",
    "InstrumentIdentity",
    "InstrumentType",
    "OptionType",
    "OrderStatus",
    "OrderType",
    "Product",
    "Segment",
    "Side",
    "Validity",
    "gateway",
]
