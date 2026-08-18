"""BrokerAdapter protocol (Phase 6.5.0.2).

The contract every broker adapter implements. Application services request
an adapter from the BrokerGateway and consume ONLY canonical models —
canonical errors (:class:`BrokerError`), canonical instrument identity and
canonical order models.

The contract is deliberately complete (auth / account / instruments /
market data / orders / trades / portfolio). Operations that are prepared
but NOT wired into the current application execution path are documented
below and must raise ``BrokerError(CAPABILITY_UNSUPPORTED)`` until a later
phase wires them — an adapter must never fake an implementation.

Methods that return raw provider payloads (``get_profile``, ``get_funds``,
``get_margin``, ``get_market_status``) are consumed ONLY by the broker
integration services (broker diagnostics / capital margin) which
canonicalize them — they are adapter-boundary returns, never domain
objects. Chain/contract methods return canonical platform structures.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.brokers.domain.capabilities import BrokerCapabilities
from app.brokers.domain.models import (
    BrokerConnectionContext,
    BrokerInstrumentMapping,
    BrokerOrderRequest,
    BrokerOrderResult,
    InstrumentIdentity,
)


class BrokerAdapter(Protocol):
    """The broker-neutral adapter contract.

    Provider-specific concepts (Upstox instrument keys, transaction types,
    product codes, API URLs, HTTP-status handling, error strings, order
    status strings, token handling) stay INSIDE implementations of this
    protocol. Domain code never sees them.
    """

    broker_id: str
    broker_name: str

    # ---- AUTHENTICATION ----
    def get_authorization_url(self, state: str) -> str:
        """Build the broker OAuth authorization URL for ``state`` (CSRF)."""
        ...

    def exchange_authorization_code(self, code: str) -> str:
        """Exchange an authorization code for an access token (server-side)."""
        ...

    def disconnect(self) -> None:
        """Release this adapter's session state. The app's auth layer owns
        session/token revocation; adapters never clear another layer's state."""
        ...

    # ---- ACCOUNT ----
    def get_profile(self) -> dict:
        """Fetch the broker-reported profile. Returns the raw broker payload;
        the broker-diagnostics service canonicalizes it into the SAFE profile
        contract. Credentials are never included."""
        ...

    def get_funds(self) -> dict:
        """Fetch account funds (raw broker payload; capital service canonicalizes)."""
        ...

    def get_margin(self, instruments: list[dict]) -> dict:
        """Fetch broker-computed margin for a basket (raw broker payload)."""
        ...

    def get_capabilities(self, profile: dict | None = None) -> BrokerCapabilities:
        """Canonical capability matrix for this broker (session/account aware)."""
        ...

    # ---- INSTRUMENTS ----
    def resolve_instrument(self, symbol: str) -> InstrumentIdentity:
        """Resolve a platform symbol to its canonical identity (pure lookup)."""
        ...

    def search_instruments(self, query: str) -> list[BrokerInstrumentMapping]:
        """Search known instruments (canonical identities + broker keys)."""
        ...

    def get_option_contracts(self, symbol: str) -> dict:
        """List a symbol's available expiries. Returns the canonical
        ``{"symbol": ..., "expiries": [...]}`` contract."""
        ...

    # ---- MARKET DATA ----
    def get_market_status(self, exchange: str) -> dict:
        """Fetch market status for an exchange feed (raw broker payload; the
        market-status engine interprets it)."""
        ...

    def get_quote(self, instrument: InstrumentIdentity) -> dict:
        """Single quote. NOT WIRED in this phase — raises
        BrokerError(CAPABILITY_UNSUPPORTED) until a later phase wires it."""
        ...

    def get_quotes(self, instruments: list[InstrumentIdentity]) -> dict:
        """Bulk quotes. NOT WIRED in this phase."""
        ...

    def get_option_chain(self, symbol: str, expiry_date: str) -> dict:
        """Option chain for one expiry. Returns the CANONICAL transformed
        chain ``{"symbol", "expiry_date", "underlying_spot_price", "chain"}``
        — the provider payload shape stays inside the adapter."""
        ...

    # ---- ORDERS (contract prepared in this phase — NOT wired) ----
    def place_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        """Submit ONE canonical order. NOT WIRED (Phase 6.5.0.2 prepares the
        contract only)."""
        ...

    def place_orders(self, requests: list[BrokerOrderRequest]) -> list[BrokerOrderResult]:
        """Submit multiple canonical orders in one logical operation. NOT WIRED."""
        ...

    def modify_order(self, broker_order_id: str, request: BrokerOrderRequest) -> BrokerOrderResult:
        """Modify an open order. NOT WIRED."""
        ...

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        """Cancel an open order. NOT WIRED."""
        ...

    def cancel_orders(self, broker_order_ids: list[str]) -> list[BrokerOrderResult]:
        """Cancel multiple orders. NOT WIRED."""
        ...

    def get_order(self, broker_order_id: str) -> BrokerOrderResult:
        """Fetch ONE order's canonical result. NOT WIRED."""
        ...

    def get_orders(self) -> list[BrokerOrderResult]:
        """Fetch the order book. NOT WIRED."""
        ...

    def get_order_history(self, broker_order_id: str) -> list[BrokerOrderResult]:
        """Fetch an order's history (status transitions). NOT WIRED."""
        ...

    # ---- TRADES (NOT WIRED) ----
    def get_trades(self) -> list[dict]:
        """Fetch executed trades. NOT WIRED."""
        ...

    def get_order_trades(self, broker_order_id: str) -> list[dict]:
        """Fetch fills belonging to one order. NOT WIRED."""
        ...

    def get_trade_history(self) -> list[dict]:
        """Fetch full trade history. NOT WIRED."""
        ...

    # ---- PORTFOLIO (NOT WIRED) ----
    def get_positions(self) -> list[dict]:
        """Fetch broker-reported open positions. NOT WIRED."""
        ...

    def get_holdings(self) -> list[dict]:
        """Fetch broker-reported holdings. NOT WIRED."""
        ...

    def get_connection_context(self) -> BrokerConnectionContext | None:
        """The user/account/connection this adapter was created for (None for
        the implicit single-connection MVP)."""
        ...


def implements_broker_adapter(obj: Any) -> bool:
    """Runtime convenience check (Protocols are structural — this is a
    convenience helper, not an enforcement mechanism)."""
    return isinstance(obj, BrokerAdapter)
