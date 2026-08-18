"""Broker-neutral enums (Phase 6.5.0.2).

Every value here is platform vocabulary. Broker-specific strings (Upstox
``transaction_type``, ``instrument_key``, product codes, order status
strings) exist ONLY inside ``app.brokers.adapters.<broker>`` and are mapped
to/from these enums at the adapter boundary.
"""

from __future__ import annotations

from enum import Enum


class BrokerId(str, Enum):
    """Identities of brokers the platform can talk to.

    Only UPSTOX has an adapter in this phase. The other values declare the
    registry's future capacity; registering a broker is what makes it
    reachable — the enum alone never enables anything.
    """

    UPSTOX = "UPSTOX"
    ZERODHA = "ZERODHA"
    DHAN = "DHAN"
    ANGEL_ONE = "ANGEL_ONE"
    FYERS = "FYERS"


BROKER_ID_UPSTOX = BrokerId.UPSTOX


class Side(str, Enum):
    """Canonical order side (the application's BUY / SELL).

    The Upstox adapter maps this to its own ``transaction_type`` inside the
    adapter — application code never sees that mapping.
    """

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Canonical order types. MARKET / LIMIT / SL / SL-M are the neutral
    names; the adapter maps them to provider-specific values."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "SL"          # stop-loss (limit) order
    STOP_LOSS_MARKET = "SL-M"  # stop-loss market order


class Product(str, Enum):
    """Canonical product (holding) types. Upstox product codes (I/D/CO/MTF)
    are mapped inside the adapter."""

    DELIVERY = "DELIVERY"
    INTRADAY = "INTRADAY"
    CO = "CO"    # cover order
    MTF = "MTF"  # margin trading facility


class Validity(str, Enum):
    """Canonical order validity. After-market orders are expressed with the
    separate ``after_market`` flag on the request, NOT by a validity value —
    the adapter maps that flag to the provider's AMO concept."""

    DAY = "DAY"
    IOC = "IOC"  # immediate-or-cancel


class OrderStatus(str, Enum):
    """Canonical broker order lifecycle.

    Provider-specific status strings are mapped to these inside each
    adapter. Application code must never branch on provider statuses
    (no ``if upstox_status == ...`` in domain code).
    """

    CREATED = "CREATED"
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class InstrumentType(str, Enum):
    INDEX = "INDEX"
    OPTION = "OPTION"
    FUTURE = "FUTURE"
    EQUITY = "EQUITY"


class OptionType(str, Enum):
    """Canonical option type. The platform's internal chain/leg convention is
    lowercase ``call``/``put``; the canonical DOMAIN uses CALL/PUT and the
    adapter maps between the two at its boundary."""

    CALL = "CALL"
    PUT = "PUT"


class Segment(str, Enum):
    """Market segments (same vocabulary as the market-status engine)."""

    EQUITY_CASH = "EQUITY_CASH"
    EQUITY_DERIVATIVES = "EQUITY_DERIVATIVES"
    INDEX_DERIVATIVES = "INDEX_DERIVATIVES"
    STOCK_DERIVATIVES = "STOCK_DERIVATIVES"
    CURRENCY = "CURRENCY"
    COMMODITY = "COMMODITY"


class ExecutionPolicy(str, Enum):
    """Broker-neutral slicing/execution policy.

    The platform must select EXACTLY ONE slicing strategy for any order.
    ``AUTO`` lets the platform decide; ``BROKER_NATIVE`` delegates slicing to
    the broker; ``PLATFORM_MANAGED`` chunks on the platform side;
    ``DISABLED`` forbids slicing. Because an order is either platform-chunked
    OR broker-native — never both — the platform can never accidentally
    double-slice (platform chunks of a broker-native order are impossible by
    construction).
    """

    AUTO = "AUTO"
    BROKER_NATIVE = "BROKER_NATIVE"
    PLATFORM_MANAGED = "PLATFORM_MANAGED"
    DISABLED = "DISABLED"
