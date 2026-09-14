"""FYERS streaming source bridge (market-data WebSocket).

Adapts a FYERS market-data WebSocket transport behind the source-neutral
StreamingSource protocol (the same surface
:class:`UpstoxStreamingSource` implements) so the Streaming Lifecycle
Manager can govern it without knowing FYERS internals:

    FYERS market-data WebSocket (transport)
        → FyersMarketDataTransport (injectable transport boundary)
        → FyersStreamingSource (this bridge)
            tick → canonical QuoteObservation (BROKER_LIVE, FYERS, provenance)
            transport state → manager events (auth failure, connectivity)
        → StreamingLifecycleManager (Day 13)

Design decisions
----------------
* **Transport boundary.** The WebSocket wire protocol (auth message
  shape, subscription symbols, FYERS message types ``cn``/``sub``/``sf``
  /``dp``/``tick_data``/``depth``) stays inside the injectable
  transport. FYERS message codes NEVER appear in this bridge's outputs
  — every tick is already a canonical observation.
* **No credentials in the bridge.** The access token lives in the
  transport (Bearer form, AD-9); the bridge never stores or logs it.
* **No fabricated timestamps or prices.** A tick without an LTP
  produces no observation; ``market_timestamp`` comes only from what
  FYERS reports.
* **Sequence continuity is unavailable from FYERS** — the data socket
  has no per-message sequence number, so ``supports_sequence = False``.
  Never invented, matching the Upstox bridge decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.brokers.adapters.fyers import mapper
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    PriceQuote,
    Provenance,
    QuoteObservation,
)

# Normalization version of this bridge's tick → canonical mapping.
STREAM_NORMALIZATION_VERSION = "1.0.0"


def _optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_ltt(value) -> datetime | None:
    """Parse FYERS ``last_traded_timestamp`` (epoch seconds) to UTC.

    Unparseable/missing input → ``None`` (never synthesized).
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


class FyersMarketDataTransport:
    """Minimal transport interface the bridge drives.

    The real WebSocket implementation (connect / authenticate /
    subscribe / unsubscribe / heartbeat / close) plugs in here. The
    default base class records calls so tests can drive the bridge
    without a socket.
    """

    def __init__(self, access_token: str, symbols_provider: Callable[[], list[str]]):
        self._access_token = access_token  # never logged, never repr'd
        self._symbols_provider = symbols_provider
        self.state: str = "disconnected"

    async def connect(self) -> None:  # pragma: no cover - real transport
        raise NotImplementedError("Real FYERS data-socket transport not wired this phase")

    async def subscribe(self, symbols: list[str]) -> None:  # pragma: no cover
        raise NotImplementedError("Real FYERS data-socket transport not wired this phase")

    async def unsubscribe(self, symbols: list[str]) -> None:  # pragma: no cover
        raise NotImplementedError("Real FYERS data-socket transport not wired this phase")

    async def close(self) -> None:  # pragma: no cover
        raise NotImplementedError("Real FYERS data-socket transport not wired this phase")

    def on_tick(self, handler: Callable[[str, dict], None]) -> None:  # pragma: no cover
        raise NotImplementedError("Real FYERS data-socket transport not wired this phase")

    def classify_error(self, exc: BaseException) -> BrokerErrorCode:
        """Transport error → canonical code (shared by bridge + manager)."""
        text = str(exc).lower()
        if "401" in text or "unauthorized" in text or "invalid token" in text or "token expired" in text:
            return BrokerErrorCode.AUTH_REQUIRED
        if "429" in text or "rate limit" in text:
            return BrokerErrorCode.RATE_LIMITED
        return BrokerErrorCode.UPSTREAM_ERROR


class FyersStreamingSource:
    """Source-neutral bridge over a FYERS market-data WebSocket transport."""

    source_id = "FYERS"
    supports_sequence = False  # FYERS data socket has no sequence numbers

    def __init__(self, transport: FyersMarketDataTransport, *, now_utc=None):
        self._transport = transport
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self._subscribed: list[str] = []
        self._connected = False
        self._wired = False
        self._observation_handlers: list[Callable] = []
        self._error_handlers: list[Callable] = []
        self._disconnect_handlers: list[Callable] = []

    # ---- protocol surface ----------------------------------------------------

    def register_observation_handler(self, handler: Callable) -> None:
        self._observation_handlers.append(handler)

    def register_error_handler(self, handler: Callable) -> None:
        self._error_handlers.append(handler)

    def register_disconnect_handler(self, handler: Callable) -> None:
        self._disconnect_handlers.append(handler)

    async def connect(self) -> None:
        await self._transport.connect()
        self._connected = True
        self._wire_transport()

    async def subscribe(self, instruments) -> None:
        self._subscribed = list(instruments)
        await self._transport.subscribe(self._subscribed)

    async def resubscribe(self) -> None:
        await self._transport.subscribe(self._subscribed)

    async def unsubscribe(self, instruments) -> None:
        await self._transport.unsubscribe(list(instruments))
        self._subscribed = [s for s in self._subscribed if s not in set(instruments)]

    async def disconnect(self) -> None:
        await self._transport.close()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._transport.state in ("connected", "live", "subscribing", "reconnecting")

    def poll(self) -> None:
        """Transport state polling hook (liveness is transport-reported)."""

    def classify_error(self, exc) -> BrokerErrorCode:
        return self._transport.classify_error(exc)

    def __repr__(self) -> str:
        return f"FyersStreamingSource(source_id={self.source_id!r})"

    # ---- transport wiring ------------------------------------------------------

    def _wire_transport(self) -> None:
        if self._wired:
            return
        self._transport.on_tick(self._on_transport_tick)
        self._wired = True

    def _on_transport_tick(self, fyers_symbol: str, tick: dict) -> None:
        """Transport tick callback → canonical QuoteObservation.

        The FYERS symbol is resolved against the platform master; ticks
        for unknown symbols are dropped (never invented). An LTP-less
        tick produces no observation — a missing price is never zero.
        """
        symbol = mapper.instrument_symbol_from_fyers(fyers_symbol)
        if symbol is None:
            return
        ltp = _optional_float(tick.get("lp"))
        if ltp is None:
            return
        from app.brokers.adapters.fyers.mapper import resolve_instrument_identity

        try:
            identity = resolve_instrument_identity(symbol)
        except BrokerError:
            return
        instrument = mapper.instrument_identity_to_normalized(identity)
        received = self._now_utc()
        observation = QuoteObservation(
            instrument=instrument,
            quote=PriceQuote(
                ltp=ltp,
                bid=_optional_float(tick.get("bid")),
                ask=_optional_float(tick.get("ask")),
                volume=_optional_float(tick.get("v")),
                oi=_optional_float(tick.get("oi")),
                source="BROKER",
            ),
            market_timestamp=_parse_ltt(tick.get("last_traded_timestamp")),
            received_timestamp=received,
            source="FYERS",
            data_mode=DataMode.BROKER_LIVE,
            provenance=Provenance(
                source="FYERS",
                collection_mode=DataMode.BROKER_LIVE.value,
                received_at=received,
                normalization_version=STREAM_NORMALIZATION_VERSION,
                contract_version=ContractVersion.v1_0_0.value,
                transformation_id=None,
            ),
            contract_version=ContractVersion.v1_0_0,
        )
        for handler in list(self._observation_handlers):
            try:
                handler(observation)
            except Exception:  # noqa: BLE001 — one consumer must not kill the bridge
                pass

    def _emit_error(self, exc: BaseException) -> None:
        for handler in list(self._error_handlers):
            try:
                handler(exc)
            except Exception:  # noqa: BLE001
                pass

    # Convenience for tests/tooling: raw-tick ingestion passthrough.
    def ingest_tick(self, fyers_symbol: str, tick: dict[str, Any]) -> None:
        self._on_transport_tick(fyers_symbol, tick)
