"""Phase 7.8E — Candle coverage / quality audit / API tests.

Exercises:

* ``generate_coverage_report`` — coverage engine
* Candle API endpoints — list, count, coverage
* Research readiness assessment
* Gap/duplicate/out-of-order detection
* Weekend/holiday classification

All tests use in-memory SQLite.  No live API calls.
"""

from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app
from app.models import NiftyCandle
from app.services.candle_coverage import (
    generate_coverage_report,
    _detect_gaps,
    _is_trading_day,
    _parse_interval_minutes,
    EXPECTED_CANDLES_PER_DAY,
    MIN_OBSERVATIONS,
    MIN_VALIDATION,
    MIN_ROBUST,
)
from app.services.token_store import set_token, clear_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db):
    """FastAPI test client with DB override and session."""
    session_id = set_token("test-token-78E")
    app.dependency_overrides[get_db] = lambda: db

    class _Headers:
        def __init__(self, sid):
            self._sid = sid

        def __enter__(self):
            return {"X-Session-Id": self._sid}

        def __exit__(self, *args):
            pass

    with _Headers(session_id) as headers:
        yield TestClient(app), headers

    app.dependency_overrides.clear()
    clear_token()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(day: int, hour: int, minute: int, **overrides) -> NiftyCandle:
    """Create a NiftyCandle at a specific IST time → stored as naive IST.

    Phase 7.24.4: timestamps are naive IST, no UTC conversion needed.
    """
    base = {
        "symbol": "NIFTY",
        "interval": "3min",
        "open_time": datetime(2026, 8, day, hour, minute),
        "open": 25500.0,
        "high": 25520.0,
        "low": 25480.0,
        "close": 25510.0,
        "volume": 15000.0,
    }
    base.update(overrides)
    return NiftyCandle(**base)


def _make_full_day(day: int) -> list[NiftyCandle]:
    """Create 125 candles for a full trading day (09:15–15:27 IST, 3-min)."""
    candles = []
    total_minutes = 9 * 60 + 15  # 09:15 IST
    for i in range(125):
        h = (total_minutes + i * 3) // 60
        m = (total_minutes + i * 3) % 60
        candles.append(_make_candle(day, h, m))
    return candles


def _populate(db, candles: list[NiftyCandle]):
    db.add_all(candles)
    db.commit()


# ===================================================================
# Coverage engine
# ===================================================================


class TestCoverageReport:
    """§11 — Coverage report generation."""

    def test_empty_db(self, db):
        report = generate_coverage_report(db)
        assert report["total_candles"] == 0
        assert report["daily_coverage"] == []
        assert report["research_readiness"]["status"] == "NOT_READY"

    def test_single_complete_day(self, db):
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db)
        assert report["total_candles"] == 125
        assert len(report["daily_coverage"]) == 1
        assert report["daily_coverage"][0]["candle_count"] == 125
        assert report["daily_coverage"][0]["is_complete"] is True
        assert report["daily_coverage"][0]["completeness_pct"] == 100.0

    def test_incomplete_day(self, db):
        """60 candles out of 125 → partial."""
        _populate(db, _make_full_day(22)[:60])
        report = generate_coverage_report(db)
        assert report["daily_coverage"][0]["candle_count"] == 60
        assert report["daily_coverage"][0]["is_complete"] is False
        assert report["daily_coverage"][0]["completeness_pct"] < 50.0

    def test_multiple_days(self, db):
        _populate(db, _make_full_day(22) + _make_full_day(23))
        report = generate_coverage_report(db)
        assert report["total_candles"] == 250
        assert len(report["daily_coverage"]) == 2

    def test_earliest_latest_candle(self, db):
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db)
        assert report["date_range"]["earliest"] is not None
        assert report["date_range"]["latest"] is not None

    def test_span_days(self, db):
        _populate(db, _make_full_day(22) + _make_full_day(25))
        report = generate_coverage_report(db)
        assert report["date_range"]["span_days"] >= 2

    def test_coverage_percentage(self, db):
        """Full day → 100% coverage."""
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db)
        assert report["summary"]["coverage_pct"] == 100.0

    def test_summary_counts(self, db):
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db)
        assert report["summary"]["complete_days"] == 1
        assert report["summary"]["partial_days"] == 0

    def test_missing_trading_days_detected(self, db):
        """Two days with data but a weekday between them missing.

        Aug 24 2026 = Monday, Aug 26 2026 = Wednesday.
        Aug 25 (Tuesday) is a missing trading day.
        """
        _populate(db, _make_full_day(24) + _make_full_day(26))  # Mon + Wed, missing Tue
        report = generate_coverage_report(db)
        assert len(report["summary"]["missing_date_ranges"]) >= 1

    def test_custom_symbol(self, db):
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db, symbol="NIFTY")
        assert report["symbol"] == "NIFTY"


# ===================================================================
# Research readiness
# ===================================================================


class TestResearchReadiness:
    """§11.2 — Research readiness assessment."""

    def test_not_ready_empty(self, db):
        report = generate_coverage_report(db)
        assert report["research_readiness"]["status"] == "NOT_READY"

    def test_not_ready_few_candles(self, db):
        _populate(db, _make_full_day(22)[:10])  # 10 candles
        report = generate_coverage_report(db)
        assert report["research_readiness"]["status"] == "NOT_READY"

    def test_partial_ready(self, db):
        """200+ candles → meets basic threshold."""
        candles = []
        for d in range(22, 24):  # 2 days = 250 candles
            candles.extend(_make_full_day(d))
        _populate(db, candles)
        report = generate_coverage_report(db)
        assert report["research_readiness"]["min_observations_met"] is True

    def test_full_validation_ready(self, db):
        """500+ candles → meets full validation threshold."""
        candles = []
        for d in range(22, 27):  # 5 days = 625 candles
            candles.extend(_make_full_day(d))
        _populate(db, candles)
        report = generate_coverage_report(db)
        assert report["research_readiness"]["full_validation_met"] is True

    def test_robust_ready(self, db):
        """3000+ candles → meets robust threshold."""
        candles = []
        for d in range(1, 26):  # 25 days = 3125 candles
            candles.extend(_make_full_day(d))
        _populate(db, candles)
        report = generate_coverage_report(db)
        assert report["research_readiness"]["robust_research_met"] is True
        assert report["research_readiness"]["status"] == "READY"


# ===================================================================
# Gap detection
# ===================================================================


class TestGapDetection:
    def test_no_gaps(self, db):
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db)
        assert report["gaps"]["intraday_gaps"] == []
        assert report["gaps"]["duplicate_timestamps"] == 0
        assert report["gaps"]["out_of_order"] == 0

    def test_intraday_gap(self, db):
        """Missing candles in the middle of a trading day."""
        candles = _make_full_day(22)
        # Remove candles at indices 10-14 (5 missing)
        del candles[10:15]
        _populate(db, candles)
        report = generate_coverage_report(db)
        assert len(report["gaps"]["intraday_gaps"]) >= 1

    def test_duplicate_timestamps(self, db):
        """Test duplicate detection at the _detect_gaps level.

        DB UNIQUE constraint prevents duplicate inserts, so we test the
        gap detection function directly with an in-memory list.
        """
        candles = _make_full_day(22)[:5]
        candles.append(_make_candle(22, 9, 15))  # duplicate of first
        gaps = _detect_gaps(candles, "3min")
        assert gaps["duplicate_timestamps"] >= 1

    def test_out_of_order(self, db):
        """Test out-of-order detection at the _detect_gaps level.

        DB query uses ORDER BY open_time, so out-of-order data is
        reordered before it reaches generate_coverage_report.  Test
        the detection function directly with an unordered list.
        """
        candles = _make_full_day(22)[:5]
        candles[0], candles[2] = candles[2], candles[0]  # swap
        gaps = _detect_gaps(candles, "3min")
        assert gaps["out_of_order"] >= 1


# ===================================================================
# Trading-day classification
# ===================================================================


class TestTradingDay:
    def test_weekday_is_trading_day(self):
        assert _is_trading_day(date(2026, 8, 24)) is True  # Monday

    def test_saturday_not_trading_day(self):
        assert _is_trading_day(date(2026, 8, 22)) is False  # Saturday

    def test_sunday_not_trading_day(self):
        assert _is_trading_day(date(2026, 8, 23)) is False  # Sunday

    def test_known_holiday_not_trading_day(self):
        assert _is_trading_day(date(2026, 8, 15)) is False  # Independence Day

    def test_parse_interval(self):
        assert _parse_interval_minutes("3min") == 3
        assert _parse_interval_minutes("5min") == 5
        assert _parse_interval_minutes("1hour") == 60
        assert _parse_interval_minutes(3) == 3


# ===================================================================
# API endpoints
# ===================================================================


class TestCandleAPI:
    """§12.3 — Candle data API endpoints."""

    def test_list_candles(self, client):
        c, headers = client
        resp = c.get("/candles", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "candles" in data
        assert "count" in data
        assert data["symbol"] == "NIFTY"

    def test_candle_count(self, client):
        c, headers = client
        resp = c.get("/candles/count", headers=headers)
        assert resp.status_code == 200
        assert "count" in resp.json()

    def test_candle_coverage(self, client):
        c, headers = client
        resp = c.get("/candles/coverage", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_candles" in data
        assert "summary" in data
        assert "research_readiness" in data

    def test_unauthenticated(self, client):
        c, _ = client
        resp = c.get("/candles")
        assert resp.status_code == 401

    def test_invalid_interval(self, client):
        c, headers = client
        resp = c.get("/candles?interval=bad", headers=headers)
        assert resp.status_code == 400

    def test_invalid_since_timestamp(self, client):
        c, headers = client
        resp = c.get("/candles?since=not-a-date", headers=headers)
        assert resp.status_code == 400

    def test_list_with_data(self, client, db):
        c, headers = client
        _populate(db, _make_full_day(22)[:3])
        resp = c.get("/candles?limit=10", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

    def test_count_with_data(self, client, db):
        c, headers = client
        _populate(db, _make_full_day(22)[:5])
        resp = c.get("/candles/count", headers=headers)
        assert resp.json()["count"] == 5

    def test_coverage_with_data(self, client, db):
        c, headers = client
        _populate(db, _make_full_day(22))
        resp = c.get("/candles/coverage", headers=headers)
        data = resp.json()
        assert data["total_candles"] == 125
        assert data["research_readiness"]["status"] == "NOT_READY"  # only 1 day


# ===================================================================
# Lot-size independence
# ===================================================================


class TestLotSizeIndependence:
    def test_coverage_report_no_lot_size(self, db):
        """Coverage report contains no lot_size fields."""
        _populate(db, _make_full_day(22))
        report = generate_coverage_report(db)
        # Check top-level keys
        for key in ("lot_size", "minimum_lot", "freeze_quantity"):
            assert key not in report
        # Check daily coverage
        for day in report["daily_coverage"]:
            for key in ("lot_size", "minimum_lot"):
                assert key not in day

    def test_api_response_no_lot_size(self, client, db):
        c, headers = client
        _populate(db, _make_full_day(22)[:3])
        resp = c.get("/candles", headers=headers)
        data = resp.json()
        for candle in data["candles"]:
            for key in ("lot_size", "minimum_lot", "freeze_quantity", "tick_size"):
                assert key not in candle
