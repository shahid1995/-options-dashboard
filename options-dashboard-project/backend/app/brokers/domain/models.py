"""Broker-neutral canonical models (Phase 6.5.0.2).

These dataclasses are the platform's vocabulary. They deliberately contain
NO broker-specific field names (no ``instrument_key``, no
``transaction_type``, no ``is_amo``, no provider product codes, no
``slice``). Provider-specific concepts are mapped to/from these models at
the adapter boundary.

Key rules:
- Optional/missing values stay ``None`` — never fabricated into 0.
- One application order may produce MULTIPLE broker orders (broker-native
  slicing), so the order RESULT carries ``broker_order_ids`` (a list), not
  a single id.
- ``quantity`` is expressed in PLATFORM units (LOTS, matching the paper
  engine); adapters convert to broker contract units at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.brokers.domain.enums import (
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


@dataclass(frozen=True)
class InstrumentIdentity:
    """Canonical identity of a tradable instrument.

    This is the platform's instrument identity — NOT a broker key. Broker
    keys (Upstox ``instrument_key``, Zerodha ``instrument_token``, ...) are
    kept in separate per-broker mappings (see
    :class:`BrokerInstrumentMapping`) so a broker key can never become the
    universal instrument ID.

    For an underlying/index identity (no concrete contract), ``expiry``,
    ``strike`` and ``option_type`` stay ``None``. ``lot_size`` and
    ``tick_size`` are populated only when known — never fabricated.
    """

    exchange: str
    segment: str  # one of Segment values
    underlying: str
    symbol: str
    instrument_type: str = InstrumentType.INDEX.value
    expiry: str | None = None          # YYYY-MM-DD
    strike: float | None = None
    option_type: str | None = None     # OptionType CALL | PUT
    lot_size: int | None = None
    tick_size: float | None = None

    @property
    def is_concrete_contract(self) -> bool:
        return self.expiry is not None and self.strike is not None and self.option_type is not None


@dataclass(frozen=True)
class BrokerInstrumentMapping:
    """One broker's mapping for a canonical instrument.

    ``broker_instrument_id`` is the broker's own key for the instrument
    (Upstox: ``instrument_key``). It lives ONLY here — inside the broker
    layer — and is resolved by adapters, never by domain code.
    """

    broker: str  # BrokerId value, e.g. "UPSTOX"
    broker_instrument_id: str | None
    identity: InstrumentIdentity


@dataclass(frozen=True)
class BrokerConnectionContext:
    """Who the broker call is for. Broker access is always scoped: a user
    reaches an account through a connection; a connection selects a broker;
    the adapter performs the call. The current single-user MVP may carry a
    single implicit connection, but the architecture never assumes one
    global token."""

    user_id: str
    broker: str  # BrokerId value, e.g. "UPSTOX"
    account_id: str | None = None


@dataclass(frozen=True)
class BrokerOrderRequest:
    """Canonical, broker-neutral order request.

    ``quantity`` is in PLATFORM units (LOTS). ``execution_policy`` selects
    exactly ONE slicing strategy (AUTO / BROKER_NATIVE / PLATFORM_MANAGED /
    DISABLED) so platform chunking and broker-native slicing can never both
    apply to one order. ``metadata`` is reserved for safe, non-credential
    extra context.
    """

    instrument: InstrumentIdentity
    side: Side
    quantity: int                      # LOTS (platform unit)
    order_type: OrderType = OrderType.MARKET
    product: Product | None = None
    validity: Validity = Validity.DAY
    price: float | None = None
    trigger_price: float | None = None
    disclosed_quantity: int | None = None
    after_market: bool = False
    market_protection: bool = False
    client_order_tag: str | None = None
    broker_account_id: str | None = None
    execution_policy: ExecutionPolicy = ExecutionPolicy.AUTO
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrokerOrderResult:
    """Normalized result of submitting/fetching one or more broker orders.

    One logical application order may produce MULTIPLE broker orders
    (broker-native slicing), so ``broker_order_ids`` is a tuple — never a
    single string. ``status`` is the canonical lifecycle state; the adapter
    maps provider statuses onto it.
    """

    broker: str  # BrokerId value, e.g. "UPSTOX"
    broker_order_ids: tuple[str, ...] = ()
    status: OrderStatus = OrderStatus.UNKNOWN
    client_order_id: str | None = None
    broker_account_id: str | None = None
    accepted_at: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
