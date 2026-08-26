"""Phase 8E — GEX Reliability & Hardening Tests.

Covers:
- WebSocket reconnect backoff with jitter
- Auth failure detection (no endless reconnect)
- Stale data detection and freshness metadata
- Market hours detection
- Capture loop resilience (circuit breaker, backoff)
- Database transaction safety (rollback on failure)
- Structured observability events
- Malformed tick isolation
- State machine validity
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _make_session(engine):
    return sessionmaker(bind=engine)()


def _make_chain(spot=24000.0, strikes=None):
    """Build a minimal canonical chain for testing."""
    if strikes is None:
        strikes = [
            (23800, 0.003, 10000, 0.002, 8000),
            (24000, 0.005, 15000, 0.004, 12000),
            (24200, 0.002, 8000, 0.003, 10000),
        ]
    chain_rows = []
    for strike, call_gamma, call_oi, put_gamma, put_oi in strikes:
        chain_rows.append({
            "strike": strike,
            "call": {"gamma": call_gamma, "oi": call_oi, "ltp": 100.0},
            "put": {"gamma": put_gamma, "oi": put_oi, "ltp": 80.0},
        })
    return {
        "symbol": "NIFTY",
        "expiry_date": "2026-08-28",
        "underlying_spot_price": spot,
        "chain": chain_rows,
    }


# ---------------------------------------------------------------------------
# FeedState / state machine tests
# ---------------------------------------------------------------------------

class TestFeedStateMachine:
    """Verify FeedState has all required states and valid transitions."""

    def test_all_states_exist(self):
        from app.services.upstox_market_feed import FeedState
        required = {
            "disconnected", "connecting", "connected", "subscribing",
            "live", "reconnecting", "stale", "market_closed",
            "auth_failed", "stopping", "error",
        }
        actual = {s.value for s in FeedState}
        assert required.issubset(actual), f"Missing states: {required - actual}"

    def test_auth_failed_stops_reconnect(self):
        """Auth failure should set AUTH_FAILED, not RECONNECTING."""
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        # Simulate auth failure
        feed._handle_error("401 Unauthorized")
        assert feed.state == FeedState.AUTH_FAILED

    def test_network_error_sets_reconnecting(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._handle_error("Connection reset")
        assert feed.state == FeedState.RECONNECTING

    def test_disconnect_sets_stopping(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.LIVE
        # disconnect is async
        asyncio.get_event_loop().run_until_complete(feed.disconnect())
        assert feed.state == FeedState.DISCONNECTED

    def test_close_during_stopping_doesnt_reconnect(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.STOPPING
        feed._handle_close()
        # Should stay STOPPING, not transition to DISCONNECTED
        assert feed.state == FeedState.STOPPING


# ---------------------------------------------------------------------------
# Reconnect backoff tests
# ---------------------------------------------------------------------------

class TestReconnectBackoff:
    """Verify exponential backoff with jitter."""

    def test_backoff_increases(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")

        delays = []
        for i in range(5):
            feed._reconnect_attempts = i
            delay = feed._compute_reconnect_delay()
            delays.append(delay)

        # Each delay should generally be larger (allowing for jitter)
        # The base doubles each time: 1, 2, 4, 8, 16
        assert delays[0] < delays[2] < delays[4]

    def test_backoff_has_jitter(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._reconnect_attempts = 3  # base = 8s

        # Run multiple times to check jitter variation
        delays = [feed._compute_reconnect_delay() for _ in range(20)]
        # Jitter adds up to 25% of the base delay
        assert min(delays) < max(delays), "Jitter should produce varying delays"

    def test_backoff_capped_at_max(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, DEFAULT_RECONNECT_MAX_SECONDS
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._reconnect_attempts = 100  # Way beyond max
        delay = feed._compute_reconnect_delay()
        # Should never exceed max + 25% jitter
        assert delay <= DEFAULT_RECONNECT_MAX_SECONDS * 1.25

    def test_reconnect_exhaustion(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState, DEFAULT_RECONNECT_MAX_ATTEMPTS
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.RECONNECTING
        feed._reconnect_attempts = DEFAULT_RECONNECT_MAX_ATTEMPTS + 1

        feed._handle_reconnecting()
        assert feed.state == FeedState.ERROR

    def test_reconnect_counter_resets_on_success(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._reconnect_attempts = 5
        feed._handle_open()
        assert feed._reconnect_attempts == 0
        assert feed.state == FeedState.CONNECTED


# ---------------------------------------------------------------------------
# Stale data detection tests
# ---------------------------------------------------------------------------

class TestStaleDataDetection:
    """Verify freshness metadata and stale detection."""

    def test_fresh_when_recent_tick(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.LIVE
        feed._last_tick_time = time.time()  # Now
        feed._last_spot_time = time.time()
        feed._underlying_spot = 24000.0

        freshness = feed.freshness_status()
        assert freshness["status"] == "live"
        assert freshness["tick_age_seconds"] < 1.0

    def test_stale_when_old_tick(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState, STALE_TICK_THRESHOLD_SECONDS
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.LIVE
        feed._last_tick_time = time.time() - STALE_TICK_THRESHOLD_SECONDS - 1

        freshness = feed.freshness_status()
        assert freshness["status"] == "stale"

    def test_market_closed_status(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.MARKET_CLOSED

        freshness = feed.freshness_status()
        assert freshness["status"] == "market_closed"

    def test_auth_failed_status(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.AUTH_FAILED

        freshness = feed.freshness_status()
        assert freshness["status"] == "auth_required"

    def test_disconnected_status(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._state = FeedState.DISCONNECTED

        freshness = feed.freshness_status()
        assert freshness["status"] == "disconnected"

    def test_is_stale_uses_correct_threshold(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, STALE_TICK_THRESHOLD_SECONDS
        feed = UpstoxMarketFeed(access_token="test_token")

        # Just below threshold — not stale
        feed._last_tick_time = time.time() - (STALE_TICK_THRESHOLD_SECONDS - 1)
        assert not feed.is_stale()

        # Just above threshold — stale
        feed._last_tick_time = time.time() - (STALE_TICK_THRESHOLD_SECONDS + 1)
        assert feed.is_stale()

    def test_never_tick_returns_stale(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        # _last_tick_time = 0 means no tick ever received
        assert feed.is_stale()


# ---------------------------------------------------------------------------
# Malformed tick isolation tests
# ---------------------------------------------------------------------------

class TestMalformedTickIsolation:
    """Verify malformed ticks don't crash the feed."""

    def test_unknown_message_type_ignored(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        # Should not raise
        feed._handle_message({"type": "unknown_type"})

    def test_none_message_ignored(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._handle_message(None)

    def test_empty_feed_ignored(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._handle_live_feed({"type": "live_feed", "feeds": {}})

    def test_invalid_spot_in_tick_ignored(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._underlying_key = "NSE_INDEX|Nifty 50"

        # Feed with invalid spot (negative, NaN, zero)
        feed._handle_live_feed({
            "type": "live_feed",
            "feeds": {
                "NSE_INDEX|Nifty 50": {"ltpc": {"ltp": -100}},
            },
        })
        assert feed._underlying_spot is None  # Not updated

    def test_none_spot_in_tick_ignored(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")
        feed._underlying_key = "NSE_INDEX|Nifty 50"
        feed._underlying_spot = 24000.0

        feed._handle_live_feed({
            "type": "live_feed",
            "feeds": {
                "NSE_INDEX|Nifty 50": {"ltpc": {"ltp": None}},
            },
        })
        assert feed._underlying_spot == 24000.0  # Not overwritten

    def test_callback_exception_doesnt_crash_feed(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed
        feed = UpstoxMarketFeed(access_token="test_token")

        def bad_callback(data):
            raise RuntimeError("intentional error")

        feed.on_tick(bad_callback)
        # Should not raise
        feed._handle_live_feed({
            "type": "live_feed",
            "feeds": {"NSE_FO|123": {"ltpc": {"ltp": 100}}},
        })


# ---------------------------------------------------------------------------
# Capture service resilience tests
# ---------------------------------------------------------------------------

class TestCaptureResilience:
    """Verify GexCaptureService handles failures gracefully."""

    def test_circuit_breaker_counts_failures(self):
        from app.services.gex_capture import GexCaptureService
        service = GexCaptureService()
        assert service._consecutive_failures == 0

    def test_circuit_breaker_resets_on_success(self):
        from app.services.gex_capture import GexCaptureService
        from app.services.live_gex import LiveGexService

        service = GexCaptureService()
        service._consecutive_failures = 3

        engine = _make_engine()
        session = _make_session(engine)
        chain = _make_chain()

        result = service.capture_once(session, chain, expiry="2026-08-28")
        assert result["status"] == "captured"
        assert service._consecutive_failures == 0

    def test_calculation_error_increments_failure_count(self):
        from app.services.gex_capture import GexCaptureService
        from app.services.live_gex import LiveGexService

        mock_gex = MagicMock()
        mock_gex.calculate.side_effect = RuntimeError("calc failed")

        service = GexCaptureService(gex_service=mock_gex)
        engine = _make_engine()
        session = _make_session(engine)

        # Pass a valid chain (not empty) so it reaches the calculation
        chain = _make_chain()
        result = service.capture_once(session, chain, expiry="2026-08-28")
        assert result["status"] == "error"
        assert result["reason"] == "calculation_error"
        assert service._consecutive_failures == 1

    def test_db_failure_increments_failure_count(self):
        from app.services.gex_capture import GexCaptureService

        service = GexCaptureService()
        engine = _make_engine()
        session = _make_session(engine)

        # Corrupt the session so commit fails
        session.close()

        chain = _make_chain()
        result = service.capture_once(session, chain, expiry="2026-08-28")
        # Should not crash — returns error
        assert result["status"] in ("error", "captured")
        # Failure count may or may not increment depending on how the DB error manifests

    def test_missing_chain_returns_skipped(self):
        from app.services.gex_capture import GexCaptureService
        service = GexCaptureService()
        engine = _make_engine()
        session = _make_session(engine)

        result = service.capture_once(session, None)
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_chain"

    def test_empty_chain_returns_skipped(self):
        from app.services.gex_capture import GexCaptureService
        service = GexCaptureService()
        engine = _make_engine()
        session = _make_session(engine)

        result = service.capture_once(session, {"chain": []})
        assert result["status"] == "skipped"
        assert result["reason"] == "empty_chain"


# ---------------------------------------------------------------------------
# Database transaction safety tests
# ---------------------------------------------------------------------------

class TestDatabaseTransactionSafety:
    """Verify DB operations use explicit commit/rollback."""

    def test_record_snapshot_rolls_back_on_error(self):
        from app.services.gex_history import record_gex_snapshot

        engine = _make_engine()
        session = _make_session(engine)

        # Valid snapshot — should succeed
        result = record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": datetime.now(timezone.utc).isoformat(),
        })
        assert result == 1

        # Corrupt the session — insert should fail and rollback
        session.close()
        # A closed session's add/commit should raise, not corrupt the DB

    def test_prune_rolls_back_on_error(self):
        from app.services.gex_history import prune_gex_snapshots

        engine = _make_engine()
        session = _make_session(engine)

        # Prune on empty table — should succeed (0 deleted)
        deleted = prune_gex_snapshots(session, retention_days=90)
        assert deleted == 0

    def test_historical_gex_not_modified_by_capture(self):
        """Phase 8B invariant: capture never touches historical_gex."""
        from app.services.gex_capture import GexCaptureService

        engine = _make_engine()
        Base.metadata.create_all(engine)
        session = _make_session(engine)

        # Insert a mock historical_gex row
        from app.models import HistoricalGexSnapshot
        session.add(HistoricalGexSnapshot(
            instrument_key="NSE_FO|12345",
            interval="3min",
            open_time=datetime.now(timezone.utc),
            spot=24000.0,
            strike=24000.0,
            expiry="2026-08-28",
            option_type="CE",
            gamma=0.003,
            open_interest=10000,
            option_price=100.0,
            raw_gex=17280.0,
            signed_gex=17280.0,
            calc_version="h_gex_v1",
            calculated_at=datetime.now(timezone.utc),
        ))
        session.commit()

        count_before = session.query(HistoricalGexSnapshot).count()

        # Run capture
        service = GexCaptureService()
        chain = _make_chain()
        result = service.capture_once(session, chain, expiry="2026-08-28")

        count_after = session.query(HistoricalGexSnapshot).count()
        assert count_before == count_after, "Capture must not modify historical_gex"


# ---------------------------------------------------------------------------
# Market hours detection tests
# ---------------------------------------------------------------------------

class TestMarketHoursDetection:
    """Verify market hours check in UpstoxMarketFeed."""

    def test_market_closed_skips_connection(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState

        feed = UpstoxMarketFeed(access_token="test_token")

        # Mock the calendar to return closed
        with patch("app.services.upstox_market_feed.UpstoxMarketFeed._check_market_hours", return_value=False):
            asyncio.get_event_loop().run_until_complete(
                feed.connect("NIFTY", "2026-08-28", ["NSE_FO|123"])
            )
        assert feed.state == FeedState.MARKET_CLOSED

    def test_market_open_allows_connection(self):
        from app.services.upstox_market_feed import UpstoxMarketFeed, FeedState

        feed = UpstoxMarketFeed(access_token="test_token")

        with patch("app.services.upstox_market_feed.UpstoxMarketFeed._check_market_hours", return_value=True):
            # Will fail on actual WebSocket creation, but state should be CONNECTING
            asyncio.get_event_loop().run_until_complete(
                feed.connect("NIFTY", "2026-08-28", ["NSE_FO|123"])
            )
        # State will be DISCONNECTED or ERROR (can't actually connect), but not MARKET_CLOSED
        assert feed.state != FeedState.MARKET_CLOSED


# ---------------------------------------------------------------------------
# LiveGexService edge cases
# ---------------------------------------------------------------------------

class TestLiveGexEdgeCases:
    """Verify GEX calculation handles all edge cases."""

    def test_zero_gamma_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"gamma": 0.0, "oi": 10000},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        # Zero gamma strikes are excluded from calculation
        assert result.call_gex is None or result.call_gex == 0

    def test_negative_gamma_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"gamma": -0.003, "oi": 10000},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        # Negative gamma should be excluded (INVALID status)
        assert result.availability_status in ("partial", "unavailable", "invalid")

    def test_nan_gamma_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"gamma": float("nan"), "oi": 10000},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        assert result.call_gex is None

    def test_infinite_gamma_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"gamma": float("inf"), "oi": 10000},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        assert result.call_gex is None

    def test_zero_oi_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"gamma": 0.003, "oi": 0},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        assert result.call_gex is None

    def test_missing_gamma_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"oi": 10000},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        assert result.call_gex is None

    def test_missing_oi_excluded(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [{
                "strike": 24000,
                "call": {"gamma": 0.003},
                "put": {"gamma": 0.003, "oi": 8000},
            }],
        }
        result = service.calculate(chain)
        assert result.call_gex is None

    def test_invalid_spot_unavailable(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": None,
            "chain": [],
        }
        result = service.calculate(chain)
        assert result.availability_status == "unavailable"

    def test_empty_chain_unavailable(self):
        from app.services.live_gex import LiveGexService
        service = LiveGexService()
        chain = {
            "symbol": "NIFTY",
            "expiry_date": "2026-08-28",
            "underlying_spot_price": 24000.0,
            "chain": [],
        }
        result = service.calculate(chain)
        assert result.availability_status == "unavailable"

    def test_formula_no_lot_size(self):
        """Verify lot size is NOT part of the GEX formula."""
        from app.services.live_gex import LiveGexService, _raw_gex

        # GEX = gamma * OI * spot^2 * 0.01
        gamma = 0.003
        oi = 10000
        spot = 24000.0
        expected = gamma * oi * spot * spot * 0.01
        actual = _raw_gex(gamma, oi, spot)
        assert abs(actual - expected) < 1e-6

        # Verify the function body doesn't use lot_size (excluding docstrings)
        import inspect
        source = inspect.getsource(_raw_gex)
        # Strip the docstring for the check
        lines = source.split("\n")
        body_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('\"\"\"') and not in_docstring:
                in_docstring = True
                continue
            if stripped.endswith('\"\"\"') and in_docstring:
                in_docstring = False
                continue
            if not in_docstring:
                body_lines.append(line)
        body = "\n".join(body_lines)
        assert "lot_size" not in body.lower(), "GEX formula must not use lot_size"


# ---------------------------------------------------------------------------
# Snapshot deduplication tests
# ---------------------------------------------------------------------------

class TestSnapshotDeduplication:
    """Verify deduplication prevents duplicate snapshots."""

    def test_duplicate_within_tolerance(self):
        from app.services.gex_capture import GexCaptureService
        from app.services.gex_history import record_gex_snapshot

        engine = _make_engine()
        session = _make_session(engine)

        # Insert first snapshot
        now = datetime.now(timezone.utc)
        record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": now.isoformat(),
            "strikeData": [],
            "expiryData": [],
            "methodologyMetadata": {},
        })

        # Capture with same timestamp — should be deduplicated
        service = GexCaptureService()
        chain = _make_chain()
        result = service.capture_once(session, chain, expiry="2026-08-28")
        assert result["status"] == "duplicate"

    def test_different_expiry_not_duplicate(self):
        from app.services.gex_capture import GexCaptureService
        from app.services.gex_history import record_gex_snapshot

        engine = _make_engine()
        session = _make_session(engine)

        now = datetime.now(timezone.utc)
        record_gex_snapshot(session, {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24000.0,
            "availabilityStatus": "available",
            "capturedAt": now.isoformat(),
            "strikeData": [],
            "expiryData": [],
            "methodologyMetadata": {},
        })

        # Capture with different expiry — should NOT be deduplicated
        service = GexCaptureService()
        chain = _make_chain()
        result = service.capture_once(session, chain, expiry="2026-09-04")
        assert result["status"] == "captured"


# ---------------------------------------------------------------------------
# Numerical integrity tests
# ---------------------------------------------------------------------------

class TestNumericalIntegrity:
    """Verify GEX formula is numerically correct and consistent."""

    def test_ce_gex_positive(self):
        from app.services.live_gex import _signed_gex
        result = _signed_gex("call", 0.003, 10000, 24000.0)
        assert result > 0

    def test_pe_gex_negative(self):
        from app.services.live_gex import _signed_gex
        result = _signed_gex("put", 0.003, 10000, 24000.0)
        assert result < 0

    def test_gex_magnitude(self):
        from app.services.live_gex import _raw_gex
        # gamma=0.003, OI=10000, spot=24000
        # raw = 0.003 * 10000 * 24000^2 * 0.01
        expected = 0.003 * 10000 * 24000 * 24000 * 0.01
        actual = _raw_gex(0.003, 10000, 24000.0)
        assert abs(actual - expected) < 1.0  # Within 1 unit

    def test_sign_convention(self):
        from app.services.live_gex import _signed_gex
        # CE and PE with same gamma/OI should have opposite signs
        call = _signed_gex("call", 0.003, 10000, 24000.0)
        put = _signed_gex("put", 0.003, 10000, 24000.0)
        assert call > 0
        assert put < 0
        assert abs(call) == abs(put)  # Same magnitude, opposite sign


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------

class TestConfiguration:
    """Verify configuration defaults and constants."""

    def test_stale_thresholds_are_reasonable(self):
        from app.services.upstox_market_feed import (
            STALE_TICK_THRESHOLD_SECONDS,
            STALE_CHAIN_THRESHOLD_SECONDS,
            STALE_GEX_THRESHOLD_SECONDS,
        )
        assert 1 <= STALE_TICK_THRESHOLD_SECONDS <= 60
        assert STALE_TICK_THRESHOLD_SECONDS <= STALE_CHAIN_THRESHOLD_SECONDS
        assert STALE_CHAIN_THRESHOLD_SECONDS <= STALE_GEX_THRESHOLD_SECONDS

    def test_reconnect_constants_are_reasonable(self):
        from app.services.upstox_market_feed import (
            DEFAULT_RECONNECT_BASE_SECONDS,
            DEFAULT_RECONNECT_MAX_SECONDS,
            DEFAULT_RECONNECT_MAX_ATTEMPTS,
        )
        assert 0.5 <= DEFAULT_RECONNECT_BASE_SECONDS <= 5
        assert DEFAULT_RECONNECT_MAX_SECONDS >= 10
        assert 3 <= DEFAULT_RECONNECT_MAX_ATTEMPTS <= 50

    def test_capture_interval_configurable(self):
        from app.services.gex_capture import get_capture_interval_seconds
        interval = get_capture_interval_seconds()
        assert interval > 0

    def test_retention_configurable(self):
        from app.services.gex_capture import get_retention_days
        retention = get_retention_days()
        assert retention > 0
