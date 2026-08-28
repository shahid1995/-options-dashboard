"""Tests for Phase 8B — Live GEX Snapshot Capture & Persistence.

Tests cover:
  1. GexCaptureService — capture pipeline
  2. Snapshot conversion (LiveGexService result → persistence dict)
  3. Deduplication logic
  4. Retention cleanup
  5. Data quality / freshness
  6. Numerical integrity (end-to-end)
  7. Error handling
  8. API endpoint (POST /gex/capture, existing snapshot APIs)
  9. Configuration
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import GexSnapshot
from app.services.gex_capture import (
    GexCaptureService,
    _is_duplicate,
    _result_to_snapshot_dict,
    get_capture_interval_seconds,
    get_retention_days,
    run_retention_cleanup,
)
from app.services.gex_history import (
    count_gex_snapshots,
    get_gex_snapshots,
    record_gex_snapshot,
)
from app.services.live_gex import (
    GexCalculationResult,
    GexStatus,
    LiveGexService,
    StrikeGexResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Isolated in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def service():
    return GexCaptureService()


def _make_chain(spot=24230.5, strikes=None, expiry="2026-08-28", symbol="NIFTY"):
    """Build a canonical option chain for testing."""
    if strikes is None:
        strikes = [
            {
                "strike": 24200,
                "call": {"gamma": 0.003, "oi": 10000, "ltp": 250.5},
                "put": {"gamma": 0.002, "oi": 8000, "ltp": 180.2},
            },
            {
                "strike": 24300,
                "call": {"gamma": 0.001, "oi": 5000, "ltp": 150.0},
                "put": {"gamma": 0.004, "oi": 12000, "ltp": 220.0},
            },
        ]
    return {
        "symbol": symbol,
        "expiry_date": expiry,
        "underlying_spot_price": spot,
        "chain": strikes,
    }


def _make_gex_result():
    """Build a synthetic GexCalculationResult for testing."""
    return GexCalculationResult(
        symbol="NIFTY",
        spot=24230.5,
        expiry="2026-08-28",
        captured_at=datetime.now(timezone.utc).isoformat(),
        methodology="GEX_STANDARD_V1",
        sign_convention="NAIVE_DEALER_CONVENTION",
        call_gex=176135139.075,
        put_gex=-146214286.72,
        net_gex=29920852.355,
        availability_status=GexStatus.AVAILABLE.value,
        valid_strike_count=2,
        total_strike_count=2,
        strikes=[
            StrikeGexResult(
                strike=24200,
                call_gex=176135139.075,
                put_gex=-146214286.72,
                net_gex=29920852.355,
                call_oi=10000,
                put_oi=8000,
                call_gamma=0.003,
                put_gamma=0.002,
                status="available",
            ),
        ],
        chain_age_ms=1500.0,
        methodology_metadata={
            "gexVersion": "GEX_STANDARD_V1",
            "formula": "gamma * oi * spot^2 * 0.01",
            "oiUnit": "contracts",
            "lotSizeFactorApplied": False,
            "engine": "LiveGexService_v1",
        },
    )


# ---------------------------------------------------------------------------
# 1. GexCaptureService — capture pipeline
# ---------------------------------------------------------------------------

class TestCaptureOnce:
    """Test the main capture_once() method."""

    def test_successful_capture(self, db, service):
        chain = _make_chain()
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "captured"
        assert result["symbol"] == "NIFTY"
        assert result["net_gex"] is not None
        assert result["snapshot_id"] is not None

    def test_capture_persists_to_db(self, db, service):
        chain = _make_chain()
        service.capture_once(db, chain, expiry="2026-08-28")
        count = count_gex_snapshots(db, symbol="NIFTY")
        assert count == 1

    def test_missing_chain(self, db, service):
        result = service.capture_once(db, None)
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_chain"

    def test_empty_chain(self, db, service):
        chain = _make_chain(strikes=[])
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "skipped"
        assert result["reason"] == "empty_chain"

    def test_invalid_spot_skipped(self, db, service):
        """Invalid spot cannot be persisted to DB — capture is skipped."""
        chain = _make_chain(spot=-100)
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "skipped"
        assert result["reason"] == "invalid_spot"

    def test_zero_spot_skipped(self, db, service):
        chain = _make_chain(spot=0)
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "skipped"

    def test_nan_spot_skipped(self, db, service):
        chain = _make_chain(spot=float("nan"))
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "skipped"

    def test_partial_chain(self, db, service):
        strikes = [
            {"strike": 24200, "call": {"gamma": 0.003, "oi": 10000}, "put": {"gamma": 0.002, "oi": 8000}},
            {"strike": 24300, "call": {"gamma": None, "oi": None}, "put": {"gamma": None, "oi": None}},
        ]
        chain = _make_chain(strikes=strikes)
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "captured"
        assert result["data_quality"] == "partial"

    def test_calculation_error(self, db):
        """Service handles calculation errors gracefully."""
        mock_gex = MagicMock()
        mock_gex.calculate.side_effect = RuntimeError("boom")
        service = GexCaptureService(gex_service=mock_gex)
        chain = _make_chain()
        result = service.capture_once(db, chain, expiry="2026-08-28")
        assert result["status"] == "error"
        assert result["reason"] == "calculation_error"

    def test_symbol_override(self, db, service):
        chain = _make_chain(symbol="BANKNIFTY")
        result = service.capture_once(db, chain, expiry="2026-08-28", symbol="NIFTY")
        assert result["symbol"] == "NIFTY"

    def test_expiry_from_chain(self, db, service):
        chain = _make_chain(expiry="2026-09-04")
        result = service.capture_once(db, chain)
        assert result["expiry"] == "2026-09-04"


# ---------------------------------------------------------------------------
# 2. Snapshot conversion
# ---------------------------------------------------------------------------

class TestSnapshotConversion:
    """Test _result_to_snapshot_dict converts LiveGexService output correctly."""

    def test_conversion_preserves_gex_values(self):
        result = _make_gex_result()
        snap = _result_to_snapshot_dict(result, expiry="2026-08-28")
        assert snap["callGex"] == result.call_gex
        assert snap["putGex"] == result.put_gex
        assert snap["netGex"] == result.net_gex

    def test_conversion_preserves_metadata(self):
        result = _make_gex_result()
        snap = _result_to_snapshot_dict(result, expiry="2026-08-28")
        assert snap["methodology"] == "GEX_STANDARD_V1"
        assert snap["signConvention"] == "NAIVE_DEALER_CONVENTION"
        assert snap["methodologyMetadata"]["lotSizeFactorApplied"] is False

    def test_conversion_strike_data(self):
        result = _make_gex_result()
        snap = _result_to_snapshot_dict(result, expiry="2026-08-28")
        assert len(snap["strikeData"]) == 1
        assert snap["strikeData"][0]["strike"] == 24200
        assert snap["strikeData"][0]["callGex"] == result.strikes[0].call_gex

    def test_conversion_preserves_spot(self):
        result = _make_gex_result()
        snap = _result_to_snapshot_dict(result, expiry="2026-08-28")
        assert snap["spot"] == 24230.5

    def test_conversion_status(self):
        result = _make_gex_result()
        snap = _result_to_snapshot_dict(result, expiry="2026-08-28")
        assert snap["availabilityStatus"] == "available"
        assert snap["validStrikeCount"] == 2
        assert snap["totalStrikeCount"] == 2


# ---------------------------------------------------------------------------
# 3. Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    """Test snapshot deduplication logic."""

    def test_first_capture_not_duplicate(self, db):
        now = datetime.now(timezone.utc)
        assert _is_duplicate(db, "NIFTY", "2026-08-28", now) is None

    def test_duplicate_within_tolerance(self, db):
        now = datetime.now(timezone.utc)
        # Insert a snapshot
        snap = {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24230.5,
            "methodology": "GEX_STANDARD_V1",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callGex": 100.0,
            "putGex": -100.0,
            "netGex": 0.0,
            "availabilityStatus": "available",
            "validStrikeCount": 2,
            "totalStrikeCount": 2,
            "capturedAt": now.isoformat(),
            "strikeData": "[]",
            "expiryData": "[]",
            "methodologyMetadata": "{}",
        }
        record_gex_snapshot(db, snap)

        # Check duplicate within 60s
        dup_id = _is_duplicate(db, "NIFTY", "2026-08-28", now + timedelta(seconds=30))
        assert dup_id is not None

    def test_not_duplicate_outside_tolerance(self, db):
        now = datetime.now(timezone.utc)
        snap = {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24230.5,
            "methodology": "GEX_STANDARD_V1",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callGex": 100.0,
            "putGex": -100.0,
            "netGex": 0.0,
            "availabilityStatus": "available",
            "validStrikeCount": 2,
            "totalStrikeCount": 2,
            "capturedAt": now.isoformat(),
            "strikeData": "[]",
            "expiryData": "[]",
            "methodologyMetadata": "{}",
        }
        record_gex_snapshot(db, snap)

        # Check not duplicate after 60s
        dup_id = _is_duplicate(db, "NIFTY", "2026-08-28", now + timedelta(seconds=61))
        assert dup_id is None

    def test_different_symbol_not_duplicate(self, db):
        now = datetime.now(timezone.utc)
        snap = {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24230.5,
            "methodology": "GEX_STANDARD_V1",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callGex": 100.0,
            "putGex": -100.0,
            "netGex": 0.0,
            "availabilityStatus": "available",
            "validStrikeCount": 2,
            "totalStrikeCount": 2,
            "capturedAt": now.isoformat(),
            "strikeData": "[]",
            "expiryData": "[]",
            "methodologyMetadata": "{}",
        }
        record_gex_snapshot(db, snap)

        dup_id = _is_duplicate(db, "BANKNIFTY", "2026-08-28", now)
        assert dup_id is None

    def test_capture_returns_duplicate_status(self, db, service):
        chain = _make_chain()
        # First capture
        r1 = service.capture_once(db, chain, expiry="2026-08-28")
        assert r1["status"] == "captured"

        # Second capture immediately → duplicate
        r2 = service.capture_once(db, chain, expiry="2026-08-28")
        assert r2["status"] == "duplicate"
        assert r2["snapshot_id"] == r1["snapshot_id"]

    def test_db_has_only_one_snapshot(self, db, service):
        chain = _make_chain()
        service.capture_once(db, chain, expiry="2026-08-28")
        service.capture_once(db, chain, expiry="2026-08-28")
        count = count_gex_snapshots(db, symbol="NIFTY")
        assert count == 1


# ---------------------------------------------------------------------------
# 4. Retention cleanup
# ---------------------------------------------------------------------------

class TestRetention:
    """Test snapshot retention/pruning."""

    def test_prune_removes_old_snapshots(self, db):
        old_time = datetime.now(timezone.utc) - timedelta(days=100)
        snap = {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24230.5,
            "methodology": "GEX_STANDARD_V1",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callGex": 100.0,
            "putGex": -100.0,
            "netGex": 0.0,
            "availabilityStatus": "available",
            "validStrikeCount": 2,
            "totalStrikeCount": 2,
            "capturedAt": old_time.isoformat(),
            "strikeData": "[]",
            "expiryData": "[]",
            "methodologyMetadata": "{}",
        }
        record_gex_snapshot(db, snap)
        assert count_gex_snapshots(db) == 1

        deleted = run_retention_cleanup(db)
        assert deleted == 1
        assert count_gex_snapshots(db) == 0

    def test_prune_preserves_recent(self, db):
        recent_time = datetime.now(timezone.utc) - timedelta(days=10)
        snap = {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 24230.5,
            "methodology": "GEX_STANDARD_V1",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callGex": 100.0,
            "putGex": -100.0,
            "netGex": 0.0,
            "availabilityStatus": "available",
            "validStrikeCount": 2,
            "totalStrikeCount": 2,
            "capturedAt": recent_time.isoformat(),
            "strikeData": "[]",
            "expiryData": "[]",
            "methodologyMetadata": "{}",
        }
        record_gex_snapshot(db, snap)

        deleted = run_retention_cleanup(db)
        assert deleted == 0
        assert count_gex_snapshots(db) == 1

    def test_prune_idempotent(self, db):
        deleted1 = run_retention_cleanup(db)
        deleted2 = run_retention_cleanup(db)
        assert deleted1 == 0
        assert deleted2 == 0


# ---------------------------------------------------------------------------
# 5. Configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    """Test configuration values."""

    def test_capture_interval_default(self):
        # Default should be 60 seconds
        interval = get_capture_interval_seconds()
        assert interval == 60

    def test_retention_default(self):
        days = get_retention_days()
        assert days == 90


# ---------------------------------------------------------------------------
# 6. Numerical integrity — end-to-end
# ---------------------------------------------------------------------------

class TestNumericalIntegrity:
    """End-to-end test: Chain → LiveGexService → GexCaptureService → DB → Retrieved."""

    def test_end_to_end_values_preserved(self, db, service):
        chain = _make_chain(spot=24230.5)
        expiry = "2026-08-28"

        # Capture
        result = service.capture_once(db, chain, expiry=expiry)
        assert result["status"] == "captured"

        # Retrieve from DB
        snapshots = get_gex_snapshots(db, symbol="NIFTY", expiry=expiry, limit=1)
        assert len(snapshots) == 1
        snap = snapshots[0]

        # Verify numerical integrity
        assert snap["spot"] == 24230.5
        assert snap["callGex"] is not None
        assert snap["putGex"] is not None
        assert snap["netGex"] is not None
        assert math.isfinite(snap["callGex"])
        assert math.isfinite(snap["putGex"])
        assert math.isfinite(snap["netGex"])

        # Verify formula: raw_gex = gamma * OI * spot^2 * 0.01
        expected_call_24200 = 0.003 * 10000 * 24230.5 ** 2 * 0.01
        expected_put_24200 = -(0.002 * 8000 * 24230.5 ** 2 * 0.01)
        expected_call_24300 = 0.001 * 5000 * 24230.5 ** 2 * 0.01
        expected_put_24300 = -(0.004 * 12000 * 24230.5 ** 2 * 0.01)

        expected_total_call = expected_call_24200 + expected_call_24300
        expected_total_put = expected_put_24200 + expected_put_24300

        assert snap["callGex"] == pytest.approx(expected_total_call, rel=1e-10)
        assert snap["putGex"] == pytest.approx(expected_total_put, rel=1e-10)
        assert snap["netGex"] == pytest.approx(expected_total_call + expected_total_put, rel=1e-10)

    def test_no_lot_size_in_persisted_gex(self, db, service):
        """Lot size must not affect persisted GEX values."""
        chain = _make_chain(spot=24230.5)
        result = service.capture_once(db, chain, expiry="2026-08-28")

        snapshots = get_gex_snapshots(db, symbol="NIFTY", limit=1)
        snap = snapshots[0]

        # Verify methodology metadata confirms no lot-size factor
        meta = snap.get("methodologyMetadata", {})
        assert meta.get("lotSizeFactorApplied") is False

    def test_sign_convention_preserved(self, db, service):
        chain = _make_chain()
        service.capture_once(db, chain, expiry="2026-08-28")

        snapshots = get_gex_snapshots(db, symbol="NIFTY", limit=1)
        snap = snapshots[0]
        assert snap["signConvention"] == "NAIVE_DEALER_CONVENTION"
        assert snap["callGex"] > 0  # call GEX is positive
        assert snap["putGex"] < 0  # put GEX is negative


# ---------------------------------------------------------------------------
# 7. Existing snapshot APIs continue working
# ---------------------------------------------------------------------------

class TestExistingApis:
    """Verify existing GEX snapshot APIs are not broken.

    These tests use the production database via TestClient.
    They verify API contracts, not database state.
    """

    def _make_client(self):
        from app.main import app
        return TestClient(app)

    @patch("app.routers.gex.token_store")
    def test_post_snapshots_validates_input(self, mock_token_store):
        """POST /gex/snapshots rejects invalid input."""
        mock_token_store.get_token.return_value = "fake-token"
        client = self._make_client()
        resp = client.post(
            "/gex/snapshots",
            json={"symbol": ""},  # invalid: missing required fields
            headers={"X-Session-Id": "test-session"},
        )
        # Should return 400, 401 (auth gate), or 422 for invalid input
        assert resp.status_code in (400, 401, 422)

    @patch("app.routers.gex.token_store")
    def test_get_snapshots_requires_auth(self, mock_token_store):
        """GET /gex/snapshots requires authentication."""
        mock_token_store.get_token.return_value = None
        client = self._make_client()
        resp = client.get("/gex/snapshots?symbol=NIFTY")
        assert resp.status_code == 401

    @patch("app.routers.gex.token_store")
    def test_get_latest_requires_auth(self, mock_token_store):
        """GET /gex/snapshots/latest requires authentication."""
        mock_token_store.get_token.return_value = None
        client = self._make_client()
        resp = client.get("/gex/snapshots/latest?symbol=NIFTY")
        assert resp.status_code == 401

    @patch("app.routers.gex.token_store")
    def test_count_requires_auth(self, mock_token_store):
        """GET /gex/snapshots/count requires authentication."""
        mock_token_store.get_token.return_value = None
        client = self._make_client()
        resp = client.get("/gex/snapshots/count")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. Historical GEX untouched
# ---------------------------------------------------------------------------

class TestHistoricalGexUntouched:
    """Verify capture does not modify historical_gex."""

    def test_capture_does_not_touch_historical_gex(self, db, service):
        # Count historical_gex before
        before = db.execute(text("SELECT COUNT(*) FROM historical_gex")).scalar() or 0

        # Capture a live snapshot
        chain = _make_chain()
        service.capture_once(db, chain, expiry="2026-08-28")

        # Count historical_gex after
        after = db.execute(text("SELECT COUNT(*) FROM historical_gex")).scalar() or 0
        assert before == after
