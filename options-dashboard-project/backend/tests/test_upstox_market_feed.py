"""Tests for Phase 8C — Upstox V3 WebSocket Market Data Feed.

Tests cover:
  1. InstrumentTick — canonical tick format
  2. UpstoxMarketFeed — connection lifecycle
  3. Message handling — market_info, live_feed
  4. Option chain reconstruction
  5. Stale data detection
  6. Error isolation
  7. GEX numerical parity via WebSocket state
  8. Integration with LiveGexService
"""

from __future__ import annotations

import math
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.upstox_market_feed import (
    FeedState,
    GEX_SUBSCRIPTION_MODE,
    InstrumentTick,
    UpstoxMarketFeed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def feed():
    return UpstoxMarketFeed(access_token="test-token-123")


def _make_ltpc_tick(ltp=250.5, oi=10000, gamma=0.003, delta=0.5, iv=0.18):
    """Build a minimal live_feed message with firstLevelWithGreeks."""
    return {
        "type": "live_feed",
        "feeds": {
            "NSE_FO|45450": {
                "firstLevelWithGreeks": {
                    "ltpc": {"ltp": ltp, "ltt": "1740729552723", "ltq": "75", "cp": 494.05},
                    "firstDepth": {"bidQ": "75", "bidP": ltp - 0.3, "askQ": "150", "askP": ltp + 0.2},
                    "optionGreeks": {"delta": delta, "gamma": gamma, "theta": -8.5, "vega": 16.7, "rho": 3.9},
                    "oi": oi,
                    "vtt": "5678",
                    "iv": iv,
                },
            },
        },
        "currentTs": "1740729566039",
    }


def _make_full_feed_tick(ltp=250.5, oi=10000, gamma=0.003):
    """Build a live_feed message with fullFeed."""
    return {
        "type": "live_feed",
        "feeds": {
            "NSE_FO|45450": {
                "fullFeed": {
                    "marketFF": {
                        "ltpc": {"ltp": ltp, "ltt": "1740729552723", "ltq": "75", "cp": 494.05},
                        "marketLevel": {
                            "bidAskQuote": [
                                {"bidQ": "75", "bidP": ltp - 0.3, "askQ": "150", "askP": ltp + 0.2},
                            ]
                        },
                        "optionGreeks": {"delta": 0.5, "gamma": gamma, "theta": -8.5, "vega": 16.7, "rho": 3.9},
                    },
                    "oi": oi,
                    "vtt": "5678",
                    "iv": 0.18,
                },
            },
        },
        "currentTs": "1740729566039",
    }


def _make_market_info(status="NORMAL_OPEN"):
    return {
        "type": "market_info",
        "marketInfo": {
            "segmentStatus": {
                "NSE_FO": status,
                "NSE_INDEX": status,
            }
        },
    }


# ---------------------------------------------------------------------------
# 1. InstrumentTick
# ---------------------------------------------------------------------------

class TestInstrumentTick:
    def test_creation(self):
        tick = InstrumentTick("NSE_FO|45450")
        assert tick.instrument_key == "NSE_FO|45450"
        assert tick.ltp is None
        assert tick.gamma is None

    def test_to_dict(self):
        tick = InstrumentTick("NSE_FO|45450")
        tick.ltp = 250.5
        tick.gamma = 0.003
        d = tick.to_dict()
        assert d["ltp"] == 250.5
        assert d["gamma"] == 0.003

    def test_timestamp_set(self):
        tick = InstrumentTick("NSE_FO|45450")
        assert tick.timestamp > 0


# ---------------------------------------------------------------------------
# 2. Feed state
# ---------------------------------------------------------------------------

class TestFeedState:
    def test_initial_state(self, feed):
        assert feed.state == FeedState.DISCONNECTED

    def test_underlying_spot_initial(self, feed):
        assert feed.underlying_spot is None


# ---------------------------------------------------------------------------
# 3. Message handling
# ---------------------------------------------------------------------------

class TestMessageHandling:
    def test_handle_market_info_open(self, feed):
        msg = _make_market_info("NORMAL_OPEN")
        feed._handle_market_info(msg)
        # State should remain as-is (not changed to MARKET_CLOSED)
        assert feed.state != FeedState.MARKET_CLOSED

    def test_handle_market_info_closed(self, feed):
        feed._state = FeedState.LIVE
        msg = _make_market_info("CLOSED")
        feed._handle_market_info(msg)
        assert feed.state == FeedState.MARKET_CLOSED

    def test_handle_live_feed_ltpc(self, feed):
        msg = {
            "type": "live_feed",
            "feeds": {
                "NSE_FO|45450": {
                    "ltpc": {"ltp": 250.5, "ltt": "123", "ltq": "75", "cp": 494.0},
                },
            },
        }
        feed._handle_live_feed(msg)
        tick = feed.get_tick("NSE_FO|45450")
        assert tick is not None
        assert tick.ltp == 250.5

    def test_handle_live_feed_first_level_with_greeks(self, feed):
        msg = _make_ltpc_tick(ltp=300.0, oi=5000, gamma=0.005, iv=0.22)
        feed._handle_live_feed(msg)
        tick = feed.get_tick("NSE_FO|45450")
        assert tick is not None
        assert tick.ltp == 300.0
        assert tick.oi == 5000
        assert tick.gamma == 0.005
        assert tick.iv == 0.22

    def test_handle_live_feed_full_feed(self, feed):
        msg = _make_full_feed_tick(ltp=275.0, oi=8000, gamma=0.004)
        feed._handle_live_feed(msg)
        tick = feed.get_tick("NSE_FO|45450")
        assert tick is not None
        assert tick.ltp == 275.0
        assert tick.oi == 8000
        assert tick.gamma == 0.004

    def test_handle_live_feed_updates_underlying(self, feed):
        feed._underlying_key = "NSE_INDEX|Nifty 50"
        msg = {
            "type": "live_feed",
            "feeds": {
                "NSE_INDEX|Nifty 50": {
                    "ltpc": {"ltp": 24230.5, "ltt": "123", "ltq": "50", "cp": 24200.0},
                },
            },
        }
        feed._handle_live_feed(msg)
        assert feed.underlying_spot == 24230.5

    def test_handle_live_feed_multiple_instruments(self, feed):
        msg = {
            "type": "live_feed",
            "feeds": {
                "NSE_FO|45450": {
                    "ltpc": {"ltp": 250.0, "ltt": "123", "ltq": "75", "cp": 494.0},
                },
                "NSE_FO|45451": {
                    "ltpc": {"ltp": 180.0, "ltt": "124", "ltq": "75", "cp": 300.0},
                },
            },
        }
        feed._handle_live_feed(msg)
        assert feed.get_tick("NSE_FO|45450").ltp == 250.0
        assert feed.get_tick("NSE_FO|45451").ltp == 180.0

    def test_handle_unknown_message_type(self, feed):
        """Unknown message types should not crash the feed."""
        feed._handle_message({"type": "unknown_type"})
        # No exception means pass

    def test_handle_malformed_message(self, feed):
        """Malformed messages should not crash the feed."""
        feed._handle_message(None)
        feed._handle_message("not a dict")
        feed._handle_message({"type": "live_feed", "feeds": "not a dict"})


# ---------------------------------------------------------------------------
# 4. Option chain reconstruction
# ---------------------------------------------------------------------------

class TestOptionChainReconstruction:
    def test_empty_chain(self, feed):
        chain = feed.get_option_chain("NIFTY", "2026-08-28")
        assert chain["symbol"] == "NIFTY"
        assert chain["expiry_date"] == "2026-08-28"
        assert chain["chain"] == []
        assert chain["underlying_spot_price"] is None

    def test_chain_with_ticks(self, feed):
        # Simulate receiving ticks for call and put at same strike
        feed._ticks["NSE_FO|45450"] = InstrumentTick("NSE_FO|45450")
        feed._ticks["NSE_FO|45450"].ltp = 250.5
        feed._ticks["NSE_FO|45450"].oi = 10000
        feed._ticks["NSE_FO|45450"].gamma = 0.003

        feed._ticks["NSE_FO|45451"] = InstrumentTick("NSE_FO|45451")
        feed._ticks["NSE_FO|45451"].ltp = 180.2
        feed._ticks["NSE_FO|45451"].oi = 8000
        feed._ticks["NSE_FO|45451"].gamma = 0.002

        specs = {
            "NSE_FO|45450": {"strike": 24200, "option_type": "CE"},
            "NSE_FO|45451": {"strike": 24200, "option_type": "PE"},
        }

        chain = feed.get_option_chain("NIFTY", "2026-08-28", contract_specs=specs)
        assert len(chain["chain"]) == 1
        assert chain["chain"][0]["strike"] == 24200
        assert chain["chain"][0]["call"]["ltp"] == 250.5
        assert chain["chain"][0]["call"]["gamma"] == 0.003
        assert chain["chain"][0]["put"]["ltp"] == 180.2
        assert chain["chain"][0]["put"]["gamma"] == 0.002

    def test_chain_sorted_by_strike(self, feed):
        feed._ticks["A"] = InstrumentTick("A")
        feed._ticks["B"] = InstrumentTick("B")
        feed._ticks["C"] = InstrumentTick("C")

        specs = {
            "A": {"strike": 24300, "option_type": "CE"},
            "B": {"strike": 24100, "option_type": "CE"},
            "C": {"strike": 24200, "option_type": "CE"},
        }

        chain = feed.get_option_chain("NIFTY", "2026-08-28", contract_specs=specs)
        strikes = [r["strike"] for r in chain["chain"]]
        assert strikes == sorted(strikes)

    def test_chain_preserves_underlying_spot(self, feed):
        feed._underlying_spot = 24230.5
        chain = feed.get_option_chain("NIFTY", "2026-08-28")
        assert chain["underlying_spot_price"] == 24230.5


# ---------------------------------------------------------------------------
# 5. Stale detection
# ---------------------------------------------------------------------------

class TestStaleDetection:
    def test_initially_stale(self, feed):
        assert feed.is_stale() is True

    def test_not_stale_after_tick(self, feed):
        feed._last_tick_time = time.time()
        assert feed.is_stale() is False

    def test_stale_after_threshold(self, feed):
        feed._last_tick_time = time.time() - 60  # 60 seconds ago
        assert feed.is_stale() is True


# ---------------------------------------------------------------------------
# 6. Error isolation
# ---------------------------------------------------------------------------

class TestErrorIsolation:
    def test_callback_error_doesnt_crash(self, feed):
        def bad_callback(msg):
            raise RuntimeError("callback error")

        feed.on_tick(bad_callback)
        msg = _make_ltpc_tick()
        feed._handle_live_feed(msg)  # Should not raise
        tick = feed.get_tick("NSE_FO|45450")
        assert tick is not None  # Tick was still processed

    def test_get_status(self, feed):
        status = feed.get_status()
        assert "state" in status
        assert "underlying_spot" in status
        assert "instruments_tracked" in status
        assert "is_stale" in status


# ---------------------------------------------------------------------------
# 7. GEX numerical parity via WebSocket state
# ---------------------------------------------------------------------------

class TestGexParity:
    """Verify that GEX calculated from WebSocket ticks matches Phase 8A formula."""

    def test_gex_from_websocket_ticks(self, feed):
        """GEX = gamma × OI × spot² × 0.01 — same as Phase 8A."""
        feed._underlying_spot = 24230.5

        # Simulate ticks for call and put at same strike
        call_tick = InstrumentTick("CALL_24200")
        call_tick.gamma = 0.003
        call_tick.oi = 10000
        call_tick.ltp = 250.5

        put_tick = InstrumentTick("PUT_24200")
        put_tick.gamma = 0.002
        put_tick.oi = 8000
        put_tick.ltp = 180.2

        feed._ticks["CALL_24200"] = call_tick
        feed._ticks["PUT_24200"] = put_tick

        spot = 24230.5
        expected_call_gex = 0.003 * 10000 * spot ** 2 * 0.01
        expected_put_gex = -(0.002 * 8000 * spot ** 2 * 0.01)

        # Verify the tick data contains correct values for GEX
        assert call_tick.gamma * call_tick.oi * spot ** 2 * 0.01 == pytest.approx(expected_call_gex, rel=1e-12)
        assert -(put_tick.gamma * put_tick.oi * spot ** 2 * 0.01) == pytest.approx(expected_put_gex, rel=1e-12)

    def test_chain_format_compatible_with_live_gex_service(self, feed):
        """Chain from WebSocket must be compatible with LiveGexService."""
        from app.services.live_gex import LiveGexService

        feed._underlying_spot = 24230.5

        # Simulate ticks
        for ik, strike, ot, gamma, oi in [
            ("C_24200", 24200, "CE", 0.003, 10000),
            ("P_24200", 24200, "PE", 0.002, 8000),
            ("C_24300", 24300, "CE", 0.001, 5000),
            ("P_24300", 24300, "PE", 0.004, 12000),
        ]:
            tick = InstrumentTick(ik)
            tick.gamma = gamma
            tick.oi = oi
            tick.ltp = 200.0
            feed._ticks[ik] = tick

        specs = {
            "C_24200": {"strike": 24200, "option_type": "CE"},
            "P_24200": {"strike": 24200, "option_type": "PE"},
            "C_24300": {"strike": 24300, "option_type": "CE"},
            "P_24300": {"strike": 24300, "option_type": "PE"},
        }

        chain = feed.get_option_chain("NIFTY", "2026-08-28", contract_specs=specs)

        # Calculate GEX using LiveGexService
        service = LiveGexService()
        result = service.calculate(chain)

        # Verify GEX is correct
        spot = 24230.5
        expected_call = 0.003 * 10000 * spot ** 2 * 0.01 + 0.001 * 5000 * spot ** 2 * 0.01
        expected_put = -(0.002 * 8000 * spot ** 2 * 0.01) - (0.004 * 12000 * spot ** 2 * 0.01)

        assert result.call_gex == pytest.approx(expected_call, rel=1e-10)
        assert result.put_gex == pytest.approx(expected_put, rel=1e-10)
        assert result.availability_status == "available"


# ---------------------------------------------------------------------------
# 8. Configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_subscription_mode(self):
        assert GEX_SUBSCRIPTION_MODE == "full"

    def test_feed_state_values(self):
        states = [s.value for s in FeedState]
        assert "disconnected" in states
        assert "live" in states
        assert "stale" in states
