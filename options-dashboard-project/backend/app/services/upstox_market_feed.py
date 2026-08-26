"""Upstox V3 WebSocket Market Data Feed — Phase 8C.

Wraps the official ``upstox_client.MarketDataStreamerV3`` to provide
live option-chain state for StrikeNova's GEX calculation pipeline.

Architecture::

    Customer's Upstox access token
            ↓
    upstox_client.MarketDataStreamerV3 (official SDK)
            ↓
    Live market-data ticks (protobuf decoded by SDK)
            ↓
    UpstoxMarketFeed (normalization + state)
            ↓
    Canonical option chain (matching transform_chain() output)
            ↓
    LiveGexService / GexCaptureService / Frontend

**Key design decisions:**

- Uses the official Upstox Python SDK for WebSocket transport and protobuf.
- Does NOT implement raw WebSocket/protobuf — the SDK handles that.
- Normalizes SDK message format to match the existing ``transform_chain()``
  output so the frontend and GEX engine work without modification.
- Maintains per-session market state (instrument → latest tick).
- Reconstructs the full option chain from accumulated tick state.
- Handles connection lifecycle, reconnection, and error isolation.

**Protocol (Upstox V3):**

- Authorization: ``Bearer <access_token>`` header
- Subscription modes: ``ltpc``, ``option_greeks``, ``full``, ``full_d30``
- For GEX: ``full`` mode provides LTP, OI, Greeks (gamma, delta, vega, theta),
  IV, volume, bid/ask depth — everything needed for GEX calculation.
- The underlying spot price must come from the index instrument
  (e.g. ``NSE_INDEX|Nifty 50``) — it is NOT included in option instrument ticks.

**Limits (Upstox free tier):**

- 2 WebSocket connections per user
- ``full`` mode: up to 2000 instruments per connection
- Combined limit: 1500 instruments across all modes
- NIFTY option chain: ~42 strikes × 2 sides = ~84 instruments + 1 index = ~85
  (well within limits)

**NOT in scope:**

- Directional trading signals
- GEX formula changes
- Historical data backfill
- Multi-user architecture (Phase 8F)
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

import upstox_client
from upstox_client.rest import ApiException

from app.brokers.adapters.upstox.mapper import UPSTOX_INSTRUMENT_KEYS as INSTRUMENT_KEYS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Subscription mode for GEX — "full" provides LTP, OI, Greeks, IV, depth
GEX_SUBSCRIPTION_MODE = "full"

# Reconnect settings
DEFAULT_RECONNECT_INTERVAL_SECONDS = 2
DEFAULT_RECONNECT_RETRY_COUNT = 10

# Stale data threshold (seconds) — if no tick received for this long, mark stale
STALE_THRESHOLD_SECONDS = 30


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------

class FeedState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SUBSCRIBING = "subscribing"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    STALE = "stale"
    MARKET_CLOSED = "market_closed"
    AUTH_FAILED = "auth_failed"


# ---------------------------------------------------------------------------
# Canonical tick format
# ---------------------------------------------------------------------------

class InstrumentTick:
    """Normalized tick for a single instrument.

    Fields match what the Upstox V3 ``full`` mode provides and what
    StrikeNova's GEX engine needs.
    """

    __slots__ = (
        "instrument_key", "ltp", "ltt", "ltq", "cp",
        "oi", "volume", "iv",
        "delta", "gamma", "theta", "vega", "rho",
        "bid_p", "bid_q", "ask_p", "ask_q",
        "timestamp",
    )

    def __init__(self, instrument_key: str):
        self.instrument_key = instrument_key
        self.ltp: Optional[float] = None
        self.ltt: Optional[str] = None
        self.ltq: Optional[str] = None
        self.cp: Optional[float] = None
        self.oi: Optional[float] = None
        self.volume: Optional[float] = None
        self.iv: Optional[float] = None
        self.delta: Optional[float] = None
        self.gamma: Optional[float] = None
        self.theta: Optional[float] = None
        self.vega: Optional[float] = None
        self.rho: Optional[float] = None
        self.bid_p: Optional[float] = None
        self.bid_q: Optional[str] = None
        self.ask_p: Optional[float] = None
        self.ask_q: Optional[str] = None
        self.timestamp: float = time.time()

    def to_dict(self) -> dict:
        return {
            "ltp": self.ltp,
            "oi": self.oi,
            "volume": self.volume,
            "iv": self.iv,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
            "bid_p": self.bid_p,
            "ask_p": self.ask_p,
            "ltt": self.ltt,
            "cp": self.cp,
        }


# ---------------------------------------------------------------------------
# Option chain parser
# ---------------------------------------------------------------------------

def _parse_instrument_key(key: str) -> dict | None:
    """Parse an Upstox instrument key like 'NSE_FO|45450' into components.

    Returns dict with exchange, segment, token, or None if unparseable.
    """
    parts = key.split("|", 1)
    if len(parts) != 2:
        return None
    exchange_segment = parts[0]
    token = parts[1]
    exchange_parts = exchange_segment.split("_", 1)
    if len(exchange_parts) != 2:
        return None
    return {
        "exchange": exchange_parts[0],
        "segment": exchange_parts[1],
        "token": token,
        "raw": key,
    }


def _extract_strike_from_instrument_key(
    instrument_key: str,
    contract_specs: dict | None = None,
) -> Optional[float]:
    """Extract strike price from an instrument key.

    If contract_specs mapping is available, use it.
    Otherwise, return None (caller must resolve from contract_specs table).
    """
    if contract_specs and instrument_key in contract_specs:
        return contract_specs[instrument_key].get("strike")
    return None


# ---------------------------------------------------------------------------
# UpstoxMarketFeed
# ---------------------------------------------------------------------------

class UpstoxMarketFeed:
    """Live market data feed using the Upstox V3 WebSocket.

    Maintains per-session market state and reconstructs the option chain
    from accumulated ticks. Thread-safe for single-event-loop usage.

    Usage::

        feed = UpstoxMarketFeed(access_token="...")
        await feed.connect("NIFTY", "2026-08-28", instrument_keys=[...])
        chain = feed.get_option_chain("NIFTY", "2026-08-28")
        # ... later
        await feed.disconnect()
    """

    def __init__(self, access_token: str):
        self._access_token = access_token
        self._state = FeedState.DISCONNECTED
        self._streamer: upstox_client.MarketDataStreamerV3 | None = None
        self._ticks: dict[str, InstrumentTick] = {}  # instrument_key → tick
        self._underlying_spot: Optional[float] = None
        self._underlying_key: Optional[str] = None
        self._subscribed_keys: set[str] = set()
        self._last_tick_time: float = 0.0
        self._on_tick_callbacks: list[Callable] = []
        self._contract_specs: dict = {}  # instrument_key → {strike, option_type, ...}

    @property
    def state(self) -> FeedState:
        return self._state

    @property
    def underlying_spot(self) -> Optional[float]:
        return self._underlying_spot

    def on_tick(self, callback: Callable):
        """Register a callback for each received tick."""
        self._on_tick_callbacks.append(callback)

    async def connect(
        self,
        symbol: str,
        expiry_date: str,
        instrument_keys: list[str],
        contract_specs: dict | None = None,
    ):
        """Connect to the Upstox V3 WebSocket and subscribe to instruments.

        Args:
            symbol: Underlying symbol (e.g. "NIFTY").
            expiry_date: Expiry date (e.g. "2026-08-28").
            instrument_keys: List of Upstox instrument keys to subscribe to.
            contract_specs: Optional mapping of instrument_key → strike/type info.
        """
        if self._state not in (FeedState.DISCONNECTED, FeedState.AUTH_FAILED):
            logger.warning("Feed already connected, ignoring connect()")
            return

        self._state = FeedState.CONNECTING
        self._contract_specs = contract_specs or {}

        # Determine underlying index key
        self._underlying_key = INSTRUMENT_KEYS.get(symbol)
        if not self._underlying_key:
            logger.error("Unknown symbol for feed", extra={"symbol": symbol})
            self._state = FeedState.DISCONNECTED
            return

        # Build full subscription list: options + underlying index
        all_keys = list(set(instrument_keys + [self._underlying_key]))

        try:
            # Create API client with access token
            configuration = upstox_client.Configuration()
            configuration.access_token = self._access_token
            api_client = upstox_client.ApiClient(configuration)

            # Create streamer
            self._streamer = upstox_client.MarketDataStreamerV3(
                api_client, all_keys, GEX_SUBSCRIPTION_MODE
            )

            # Enable auto-reconnect
            self._streamer.auto_reconnect(
                enable=True,
                interval=DEFAULT_RECONNECT_INTERVAL_SECONDS,
                retry_count=DEFAULT_RECONNECT_RETRY_COUNT,
            )

            # Register event handlers
            self._streamer.on("open", self._handle_open)
            self._streamer.on("message", self._handle_message)
            self._streamer.on("close", self._handle_close)
            self._streamer.on("error", self._handle_error)
            self._streamer.on("reconnecting", self._handle_reconnecting)

            # Connect (non-blocking — the SDK handles the event loop)
            self._streamer.connect()

            logger.info(
                "Upstox market feed connecting",
                extra={
                    "symbol": symbol,
                    "expiry": expiry_date,
                    "instruments": len(all_keys),
                    "underlying": self._underlying_key,
                },
            )

        except ApiException as e:
            logger.error(
                "Upstox feed connection failed",
                extra={"error": str(e)},
            )
            self._state = FeedState.AUTH_FAILED
        except Exception as e:
            logger.error(
                "Upstox feed unexpected error",
                extra={"error": str(e)},
                exc_info=True,
            )
            self._state = FeedState.DISCONNECTED

    async def disconnect(self):
        """Disconnect from the WebSocket feed."""
        if self._streamer:
            try:
                self._streamer.disconnect()
            except Exception:
                pass
        self._state = FeedState.DISCONNECTED
        logger.info("Upstox market feed disconnected")

    def _handle_open(self):
        """Called when the WebSocket connection opens."""
        self._state = FeedState.CONNECTED
        logger.info("Upstox market feed connected")

    def _handle_message(self, message):
        """Called for each incoming market data message.

        The SDK decodes protobuf and passes a dict with:
          - type: "market_info" | "live_feed"
          - feeds: {instrument_key: {ltpc, optionGreeks, ...}}
          - currentTs: timestamp
        """
        try:
            msg_type = message.get("type") if isinstance(message, dict) else None

            if msg_type == "market_info":
                self._handle_market_info(message)
                return

            if msg_type == "live_feed":
                self._handle_live_feed(message)
                return

            # Unknown message type — ignore gracefully
            logger.debug("Unknown feed message type", extra={"type": msg_type})

        except Exception as e:
            # Never let a malformed tick crash the feed
            logger.warning(
                "Error processing feed message",
                extra={"error": str(e)},
                exc_info=True,
            )

    def _handle_market_info(self, message: dict):
        """Handle market status message."""
        market_info = message.get("marketInfo", {})
        segment_status = market_info.get("segmentStatus", {})

        # Check if NSE_FO is open
        nse_fo_status = segment_status.get("NSE_FO", "")
        if "CLOSE" in nse_fo_status.upper():
            self._state = FeedState.MARKET_CLOSED
            logger.info(
                "Market closed per feed",
                extra={"nse_fo_status": nse_fo_status},
            )
        else:
            # Market is open — transition to LIVE if we were CONNECTED
            if self._state == FeedState.CONNECTED:
                self._state = FeedState.LIVE

    def _handle_live_feed(self, message: dict):
        """Handle live market data tick."""
        feeds = message.get("feeds", {})
        self._last_tick_time = time.time()

        for instrument_key, feed_data in feeds.items():
            self._process_instrument_tick(instrument_key, feed_data)

        # Update underlying spot from index tick
        if self._underlying_key and self._underlying_key in feeds:
            idx_feed = feeds[self._underlying_key]
            ltpc = idx_feed.get("ltpc") or idx_feed.get("fullFeed", {}).get("marketFF", {}).get("ltpc", {})
            spot = ltpc.get("ltp")
            if spot is not None and isinstance(spot, (int, float)) and math.isfinite(spot) and spot > 0:
                self._underlying_spot = spot

        # Fire callbacks
        for cb in self._on_tick_callbacks:
            try:
                cb(feeds)
            except Exception as e:
                logger.warning("Tick callback error", extra={"error": str(e)})

    def _process_instrument_tick(self, instrument_key: str, feed_data: dict):
        """Process a single instrument's tick data."""
        tick = self._ticks.get(instrument_key)
        if tick is None:
            tick = InstrumentTick(instrument_key)
            self._ticks[instrument_key] = tick

        # Extract from firstLevelWithGreeks (option_greeks mode)
        flwg = feed_data.get("firstLevelWithGreeks")
        if flwg:
            ltpc = flwg.get("ltpc", {})
            greeks = flwg.get("optionGreeks", {})
            depth = flwg.get("firstDepth", {})

            tick.ltp = ltpc.get("ltp")
            tick.ltt = ltpc.get("ltt")
            tick.ltq = ltpc.get("ltq")
            tick.cp = ltpc.get("cp")
            tick.oi = flwg.get("oi")
            tick.volume = flwg.get("vtt")
            tick.iv = flwg.get("iv")
            tick.delta = greeks.get("delta")
            tick.gamma = greeks.get("gamma")
            tick.theta = greeks.get("theta")
            tick.vega = greeks.get("vega")
            tick.rho = greeks.get("rho")
            tick.bid_p = depth.get("bidP")
            tick.bid_q = depth.get("bidQ")
            tick.ask_p = depth.get("askP")
            tick.ask_q = depth.get("askQ")
            tick.timestamp = time.time()
            return

        # Extract from fullFeed (full mode)
        full_feed = feed_data.get("fullFeed")
        if full_feed:
            market_ff = full_feed.get("marketFF", {})
            ltpc = market_ff.get("ltpc", {})
            greeks = market_ff.get("optionGreeks", {})
            market_level = market_ff.get("marketLevel", {})
            bid_ask = market_level.get("bidAskQuote", [{}])

            tick.ltp = ltpc.get("ltp")
            tick.ltt = ltpc.get("ltt")
            tick.ltq = ltpc.get("ltq")
            tick.cp = ltpc.get("cp")
            tick.oi = full_feed.get("oi")
            tick.volume = full_feed.get("vtt")
            tick.iv = full_feed.get("iv")
            tick.delta = greeks.get("delta")
            tick.gamma = greeks.get("gamma")
            tick.theta = greeks.get("theta")
            tick.vega = greeks.get("vega")
            tick.rho = greeks.get("rho")
            if bid_ask:
                tick.bid_p = bid_ask[0].get("bidP")
                tick.bid_q = bid_ask[0].get("bidQ")
                tick.ask_p = bid_ask[0].get("askP")
                tick.ask_q = bid_ask[0].get("askQ")
            tick.timestamp = time.time()
            return

        # Extract from ltpc only (minimal data)
        ltpc = feed_data.get("ltpc", {})
        if ltpc:
            tick.ltp = ltpc.get("ltp")
            tick.ltt = ltpc.get("ltt")
            tick.ltq = ltpc.get("ltq")
            tick.cp = ltpc.get("cp")
            tick.timestamp = time.time()

    def _handle_close(self):
        """Called when the WebSocket closes."""
        self._state = FeedState.DISCONNECTED
        logger.info("Upstox market feed connection closed")

    def _handle_error(self, error):
        """Called on WebSocket error."""
        logger.warning("Upstox market feed error", extra={"error": str(error)})
        self._state = FeedState.RECONNECTING

    def _handle_reconnecting(self):
        """Called when auto-reconnect starts."""
        self._state = FeedState.RECONNECTING
        logger.info("Upstox market feed reconnecting")

    def is_stale(self) -> bool:
        """Check if the feed data is stale (no ticks received recently)."""
        if self._last_tick_time == 0:
            return True
        return (time.time() - self._last_tick_time) > STALE_THRESHOLD_SECONDS

    def get_tick(self, instrument_key: str) -> InstrumentTick | None:
        """Get the latest tick for an instrument."""
        return self._ticks.get(instrument_key)

    def get_all_ticks(self) -> dict[str, InstrumentTick]:
        """Get all accumulated ticks."""
        return dict(self._ticks)

    def get_option_chain(
        self,
        symbol: str,
        expiry_date: str,
        contract_specs: dict | None = None,
    ) -> dict:
        """Reconstruct the canonical option chain from accumulated ticks.

        Returns a dict matching the exact format of ``transform_chain()``::

            {
                "symbol": "NIFTY",
                "expiry_date": "2026-08-28",
                "underlying_spot_price": 24230.5,
                "chain": [
                    {
                        "strike": 24200,
                        "call": {"gamma": ..., "oi": ..., "ltp": ..., ...},
                        "put": {"gamma": ..., "oi": ..., "ltp": ..., ...},
                    },
                    ...
                ]
            }

        This is the canonical format consumed by:
        - LiveGexService (Phase 8A)
        - GexCaptureService (Phase 8B)
        - Frontend useChainFeed.js
        """
        specs = contract_specs or self._contract_specs

        # Build strike → {call: tick, put: tick} mapping
        strike_map: dict[float, dict] = {}

        for ik, tick in self._ticks.items():
            # Skip the underlying index
            if ik == self._underlying_key:
                continue

            # Resolve strike and option type from contract specs
            spec = specs.get(ik)
            if spec is None:
                # Try to extract from instrument key (fallback)
                continue

            strike = spec.get("strike")
            option_type = spec.get("option_type", "").upper()

            if strike is None or option_type not in ("CE", "PE"):
                continue

            side = "call" if option_type == "CE" else "put"

            if strike not in strike_map:
                strike_map[strike] = {"call": None, "put": None}

            # Convert tick to the format expected by transform_chain() output
            strike_map[strike][side] = {
                "ltp": tick.ltp,
                "oi": tick.oi,
                "volume": tick.volume,
                "iv": tick.iv,
                "delta": tick.delta,
                "gamma": tick.gamma,
                "theta": tick.theta,
                "vega": tick.vega,
                "rho": tick.rho,
                "pop": None,  # Upstox V3 doesn't provide pop
                "quote_timestamp": tick.ltt,
                "chg_oi": None,  # Not available from WebSocket ticks
            }

        # Build sorted chain rows
        chain = []
        for strike in sorted(strike_map.keys()):
            sides = strike_map[strike]
            chain.append({
                "strike": strike,
                "call": sides["call"] or {},
                "put": sides["put"] or {},
            })

        return {
            "symbol": symbol,
            "expiry_date": expiry_date,
            "underlying_spot_price": self._underlying_spot,
            "chain": chain,
        }

    def get_status(self) -> dict:
        """Get current feed status for monitoring."""
        return {
            "state": self._state.value,
            "underlying_spot": self._underlying_spot,
            "instruments_tracked": len(self._ticks),
            "subscribed_keys": len(self._subscribed_keys),
            "last_tick_age_seconds": (
                round(time.time() - self._last_tick_time, 1)
                if self._last_tick_time > 0
                else None
            ),
            "is_stale": self.is_stale(),
        }
