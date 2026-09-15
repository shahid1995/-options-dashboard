"""Upstox streaming source bridge (Day 13).

Adapts the existing Phase-8C ``UpstoxMarketFeed`` (official SDK WebSocket
transport + protobuf + tick state) behind the source-neutral
:class:`~app.market_data.streaming.StreamingSource` protocol so the
Streaming Lifecycle Manager can govern it without knowing Upstox internals:

    Upstox V3 SDK (MarketDataStreamerV3)
        → UpstoxMarketFeed (existing: transport, ticks, chain state)
        → UpstoxStreamingSource (this bridge)
            tick → canonical QuoteObservation (BROKER_LIVE, UPSTOX, provenance)
            feed state → manager events (auth failure, connectivity)
        → StreamingLifecycleManager (Day 13)

Design decisions
----------------
* **REUSE, not rewrite.**  The SDK transport, protobuf decoding, token
  handling and tick state stay in ``UpstoxMarketFeed``.  The bridge only
  projects feed events into the source-neutral protocol.
* **No credentials in the bridge.**  The access token lives in the feed;
  the bridge never stores or logs it.
* **Sequence continuity is unavailable from Upstox.**  The V3 feed message
  carries ``currentTs`` (an exchange timestamp) but no per-message sequence
  number, so ``supports_sequence = False`` — sequence numbers are NEVER
  invented.  This limitation is documented here and in the Day-13 plan.
* **LTP-less ticks produce no quote.**  A tick with ``ltp is None`` is
  skipped — a missing price is never fabricated as zero.
* **Timestamps stay distinct.**  ``market_timestamp`` comes from the
  exchange ``ltt`` (epoch-ms, normalized to UTC); ``received_timestamp`` is
  the bridge clock.  They are never conflated.
* **SDK auto-reconnect interplay.**  The feed enables the SDK's own
  transport-level auto-reconnect; the bridge reports the feed as connected
  while the SDK is reconnecting so the manager does not fight the transport.
  The manager's bounded backoff / resubscription policy applies to
  source-level disconnects and failures surfaced through this bridge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.brokers.adapters.upstox.mapper import upstox_timestamp_to_datetime
from app.brokers.domain.errors import BrokerError, BrokerErrorCode
from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    NormalizedInstrument,
    PriceQuote,
    Provenance,
    QuoteObservation,
    Side,
)
from app.services.upstox_market_feed import FeedState, _parse_instrument_key

# Normalization version of this bridge's tick → canonical mapping.
STREAM_NORMALIZATION_VERSION = "1.0.0"


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class UpstoxStreamingSource:
    """Source-neutral bridge over :class:`UpstoxMarketFeed`."""

    source_id = "UPSTOX"
    supports_sequence = False  # Upstox V3 has no per-message sequence numbers

    # Feed states in which the transport is (or is being) connected; the SDK
    # owns transport-level reconnect, so the manager must not double-drive it.
    _CONNECTED_FEED_STATES = frozenset(
        {
            FeedState.CONNECTED,
            FeedState.LIVE,
            FeedState.SUBSCRIBING,
            FeedState.RECONNECTING,
            FeedState.STALE,
        }
    )

    def __init__(
        self,
        feed,
        *,
        symbol: str,
        expiry_date: str,
        contract_specs: dict | None = None,
        now_utc: Callable[[], datetime] | None = None,
    ):
        self._feed = feed
        self._symbol = symbol
        self._expiry_date = expiry_date
        self._specs: dict = dict(contract_specs or {})
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self._instruments: list[str] = []
        self._wired = False
        self._last_state: FeedState | None = None
        self._observation_handlers: list[Callable] = []
        self._error_handlers: list[Callable] = []
        self._disconnect_handlers: list[Callable] = []

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------

    def register_observation_handler(self, handler: Callable) -> None:
        self._observation_handlers.append(handler)

    def register_error_handler(self, handler: Callable) -> None:
        self._error_handlers.append(handler)

    def register_disconnect_handler(self, handler: Callable) -> None:
        self._disconnect_handlers.append(handler)

    async def connect(self) -> None:
        # The feed's connect() performs connection + subscription together,
        # so the actual transport work happens in subscribe()/resubscribe().
        self._connected_requested = True

    async def subscribe(self, instruments) -> None:
        self._instruments = list(instruments)
        await self._feed.connect(self._symbol, self._expiry_date, self._instruments, self._specs)
        self._wire_feed()

    async def resubscribe(self) -> None:
        await self._feed.connect(self._symbol, self._expiry_date, self._instruments, self._specs)
        self._wire_feed()

    async def disconnect(self) -> None:
        await self._feed.disconnect()

    def is_connected(self) -> bool:
        try:
            return self._feed.state in self._CONNECTED_FEED_STATES
        except Exception:  # noqa: BLE001
            return False

    def poll(self) -> None:
        """Translate feed-level state into manager events (e.g. auth failure)."""
        try:
            state = self._feed.state
        except Exception:  # noqa: BLE001
            return
        if state is FeedState.AUTH_FAILED and self._last_state is not FeedState.AUTH_FAILED:
            self._emit_error(
                BrokerError(
                    BrokerErrorCode.AUTH_REQUIRED,
                    "Upstox stream authentication failed (401); the stream will not reconnect.",
                )
            )
        self._last_state = state

    def classify_error(self, exc) -> BrokerErrorCode:
        """Map Upstox/feed errors onto the canonical broker taxonomy."""
        text = str(exc).lower()
        if "401" in text or "unauthorized" in text or "invalid token" in text or "token expired" in text:
            return BrokerErrorCode.AUTH_REQUIRED
        if "429" in text or "rate limit" in text or "rate_limit" in text:
            return BrokerErrorCode.RATE_LIMITED
        return BrokerErrorCode.UPSTREAM_ERROR

    def __repr__(self) -> str:
        return f"UpstoxStreamingSource(source_id={self.source_id!r}, symbol={self._symbol!r})"

    # ------------------------------------------------------------------
    # Feed wiring
    # ------------------------------------------------------------------

    def _wire_feed(self) -> None:
        if self._wired:
            return
        self._feed.on_tick(self._on_feed_tick)
        self._wired = True

    def _on_feed_tick(self, feeds: dict) -> None:
        """Feed tick callback → canonical QuoteObservation per instrument."""
        for instrument_key in (feeds or {}).keys():
            tick = self._feed.get_tick(instrument_key)
            observation = self._tick_to_observation(instrument_key, tick)
            if observation is None:
                continue  # no LTP → no fabricated quote
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

    # ------------------------------------------------------------------
    # Tick → canonical observation
    # ------------------------------------------------------------------

    def _tick_to_observation(self, instrument_key: str, tick) -> QuoteObservation | None:
        """Map one feed tick to a canonical Day-9 QuoteObservation.

        A tick without an LTP yields ``None`` — a missing price is never
        fabricated as zero.
        """
        if tick is None or tick.ltp is None:
            return None

        parsed = _parse_instrument_key(instrument_key) or {}
        spec = self._specs.get(instrument_key) or {}
        option_type = str(spec.get("option_type") or "").upper()

        if option_type in ("CE", "PE"):
            instrument = NormalizedInstrument(
                exchange=parsed.get("exchange", "NSE"),
                segment=parsed.get("segment", "FO"),
                underlying=self._symbol,
                symbol=instrument_key,
                instrument_type="OPTION",
                expiry=self._expiry_date,
                strike=_optional_float(spec.get("strike")),
                option_type=Side.CALL if option_type == "CE" else Side.PUT,
            )
        else:
            instrument = NormalizedInstrument(
                exchange=parsed.get("exchange", "NSE"),
                segment=parsed.get("segment", "INDEX"),
                underlying=self._symbol,
                symbol=instrument_key,
                instrument_type="INDEX",
            )

        received = self._now_utc()
        return QuoteObservation(
            instrument=instrument,
            quote=PriceQuote(
                ltp=float(tick.ltp),
                bid=_optional_float(tick.bid_p),
                ask=_optional_float(tick.ask_p),
                bid_quantity=_optional_int(tick.bid_q),
                ask_quantity=_optional_int(tick.ask_q),
                volume=_optional_float(tick.volume),
                oi=_optional_float(tick.oi),
                source="BROKER",
            ),
            market_timestamp=upstox_timestamp_to_datetime(tick.ltt),
            received_timestamp=received,
            source="UPSTOX",
            data_mode=DataMode.BROKER_LIVE,
            provenance=Provenance(
                source="UPSTOX",
                collection_mode=DataMode.BROKER_LIVE.value,
                received_at=received,
                normalization_version=STREAM_NORMALIZATION_VERSION,
                contract_version=ContractVersion.v1_0_0.value,
                transformation_id=None,
            ),
            contract_version=ContractVersion.v1_0_0,
        )