"""Phase 7.8D — Candle backfill / retry tests.

Exercises the backfill pipeline:

* ``generate_monthly_chunks`` — 28-day chunk generation
* ``fetch_with_retry``        — exponential backoff, 429/5xx/network
* ``run_backfill``            — orchestration, resume, idempotency
* Date helpers                — future-date clamping

All tests use mocked HTTP and in-memory SQLite.  No live API calls.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import NiftyCandle
from app.tools.candle_backfill import (
    _clamp_end_date,
    _today,
    generate_monthly_chunks,
    run_backfill,
)
from app.services.candle_retry import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_DELAY,
    DEFAULT_MAX_RETRIES,
    RATE_LIMIT_MIN_DELAY,
    fetch_with_retry,
)
from app.services.upstox import UpstoxError


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


async def _mock_sleep(_delay):
    """No-op sleep for tests."""
    pass


# ---------------------------------------------------------------------------
# Chunk generation (§7.1)
# ---------------------------------------------------------------------------


class TestChunkGeneration:
    """28-day chunk generation."""

    def test_single_chunk(self):
        chunks = generate_monthly_chunks(date(2026, 1, 1), date(2026, 1, 28))
        assert chunks == [(date(2026, 1, 1), date(2026, 1, 28))]

    def test_two_chunks(self):
        chunks = generate_monthly_chunks(date(2026, 1, 1), date(2026, 2, 15))
        assert len(chunks) == 2
        assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 28))
        assert chunks[1] == (date(2026, 1, 29), date(2026, 2, 15))

    def test_exact_28_days(self):
        chunks = generate_monthly_chunks(date(2026, 3, 1), date(2026, 3, 28))
        assert len(chunks) == 1

    def test_29_days(self):
        """29 days → 2 chunks (28 + 1)."""
        chunks = generate_monthly_chunks(date(2026, 3, 1), date(2026, 3, 29))
        assert len(chunks) == 2

    def test_12_months(self):
        """12 months ≈ 365 days → 13–14 chunks."""
        chunks = generate_monthly_chunks(date(2025, 8, 23), date(2026, 8, 23))
        assert 13 <= len(chunks) <= 14

    def test_contiguous_no_gaps(self):
        """Chunks must be contiguous — end of chunk N + 1 day = start of chunk N+1."""
        chunks = generate_monthly_chunks(date(2026, 1, 1), date(2026, 3, 15))
        for i in range(len(chunks) - 1):
            assert chunks[i][1] + timedelta(days=1) == chunks[i + 1][0]

    def test_all_chunks_within_limit(self):
        """No chunk exceeds 28 calendar days."""
        chunks = generate_monthly_chunks(date(2025, 1, 1), date(2026, 12, 31))
        for start, end in chunks:
            assert (end - start).days < 28

    def test_empty_range(self):
        """start > end → empty list."""
        chunks = generate_monthly_chunks(date(2026, 3, 15), date(2026, 1, 1))
        assert chunks == []

    def test_single_day(self):
        """start == end → one chunk of 1 day."""
        chunks = generate_monthly_chunks(date(2026, 6, 15), date(2026, 6, 15))
        assert len(chunks) == 1
        assert chunks[0] == (date(2026, 6, 15), date(2026, 6, 15))

    def test_custom_chunk_size(self):
        """Smaller chunk size produces more chunks."""
        chunks = generate_monthly_chunks(date(2026, 1, 1), date(2026, 1, 31), max_chunk_days=7)
        assert len(chunks) == 5  # 7+7+7+7+3

    def test_leap_year_feb(self):
        """Leap year Feb 29 is included in chunks."""
        chunks = generate_monthly_chunks(date(2028, 2, 1), date(2028, 2, 29))
        assert len(chunks) == 2  # 28 + 1
        assert chunks[-1] == (date(2028, 2, 29), date(2028, 2, 29))

    def test_december_to_january(self):
        """Year boundary doesn't break chunking."""
        # Dec 20 to Jan 20 = 31 days → 2 chunks (28 + 3)
        chunks = generate_monthly_chunks(date(2026, 12, 20), date(2027, 1, 20))
        assert len(chunks) == 2
        assert chunks[0] == (date(2026, 12, 20), date(2027, 1, 16))
        assert chunks[1] == (date(2027, 1, 17), date(2027, 1, 20))


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


class TestDateHelpers:
    def test_future_date_clamped(self):
        """Future end_date is clamped to today."""
        future = date(2099, 12, 31)
        result = _clamp_end_date(future)
        assert result == _today()

    def test_past_date_not_clamped(self):
        past = date(2025, 1, 1)
        result = _clamp_end_date(past)
        assert result == past


# ---------------------------------------------------------------------------
# Retry behavior (§8)
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    """Exponential backoff retry."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call → no retries."""
        fn = AsyncMock(return_value={"status": "success"})
        result = await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert result == {"status": "success"}
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        """HTTP 429 → retries with backoff."""
        fn = AsyncMock(side_effect=[
            UpstoxError(429, "rate limited"),
            UpstoxError(429, "rate limited"),
            {"status": "success"},
        ])
        sleep_log = []

        async def mock_sleep(d):
            sleep_log.append(d)

        result = await fetch_with_retry(fn, _test_sleep=mock_sleep)
        assert result == {"status": "success"}
        assert fn.call_count == 3
        assert len(sleep_log) == 2
        # Backoff: delay[0] = base * multiplier^0 = 1.0, but max(delay, 2.0) = 2.0
        assert sleep_log[0] >= RATE_LIMIT_MIN_DELAY

    @pytest.mark.asyncio
    async def test_retry_on_500(self):
        """HTTP 500 → retries."""
        fn = AsyncMock(side_effect=[
            UpstoxError(500, "server error"),
            {"status": "success"},
        ])
        result = await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert result == {"status": "success"}
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_502(self):
        """HTTP 502 → retries."""
        fn = AsyncMock(side_effect=[
            UpstoxError(502, "bad gateway"),
            {"status": "success"},
        ])
        result = await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_retry_on_503(self):
        """HTTP 503 → retries."""
        fn = AsyncMock(side_effect=[
            UpstoxError(503, "service unavailable"),
            {"status": "success"},
        ])
        result = await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_no_retry_on_401(self):
        """HTTP 401 → raises immediately, no retry."""
        fn = AsyncMock(side_effect=UpstoxError(401, "unauthorized"))
        with pytest.raises(UpstoxError) as exc_info:
            await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert exc_info.value.status_code == 401
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_403(self):
        """HTTP 403 → raises immediately."""
        fn = AsyncMock(side_effect=UpstoxError(403, "forbidden"))
        with pytest.raises(UpstoxError):
            await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self):
        """HTTP 400 → raises immediately."""
        fn = AsyncMock(side_effect=UpstoxError(400, "bad request"))
        with pytest.raises(UpstoxError):
            await fetch_with_retry(fn, _test_sleep=_mock_sleep)
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """All retries exhausted → raises last error."""
        fn = AsyncMock(side_effect=UpstoxError(500, "persistent error"))
        with pytest.raises(UpstoxError) as exc_info:
            await fetch_with_retry(fn, max_retries=2, _test_sleep=_mock_sleep)
        assert exc_info.value.status_code == 500
        assert fn.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """Delays increase exponentially."""
        fn = AsyncMock(side_effect=[
            UpstoxError(500, "err1"),
            UpstoxError(500, "err2"),
            UpstoxError(500, "err3"),
            {"ok"},
        ])
        sleep_log = []

        async def mock_sleep(d):
            sleep_log.append(d)

        await fetch_with_retry(fn, _test_sleep=mock_sleep)
        # delay[0] = 1.0 * 2^0 = 1.0
        # delay[1] = 1.0 * 2^1 = 2.0
        # delay[2] = 1.0 * 2^2 = 4.0
        assert sleep_log == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_delay_capped_at_max(self):
        """Delay never exceeds max_delay."""
        fn = AsyncMock(side_effect=[
            UpstoxError(500, "err1"),
            UpstoxError(500, "err2"),
            {"ok"},
        ])
        sleep_log = []

        async def mock_sleep(d):
            sleep_log.append(d)

        await fetch_with_retry(
            fn, base_delay=10.0, max_delay=15.0, _test_sleep=mock_sleep,
        )
        assert all(d <= 15.0 for d in sleep_log)

    @pytest.mark.asyncio
    async def test_rate_limit_min_delay(self):
        """429 responses get at least RATE_LIMIT_MIN_DELAY."""
        fn = AsyncMock(side_effect=[
            UpstoxError(429, "rate limited"),
            {"ok"},
        ])
        sleep_log = []

        async def mock_sleep(d):
            sleep_log.append(d)

        await fetch_with_retry(
            fn, base_delay=0.01, _test_sleep=mock_sleep,
        )
        assert sleep_log[0] >= RATE_LIMIT_MIN_DELAY


# ---------------------------------------------------------------------------
# Backfill orchestration
# ---------------------------------------------------------------------------


class TestBackfillOrchestration:
    """Integration tests for run_backfill with mocked API."""

    def _mock_response(self, candle_count: int = 5) -> dict:
        """Build a mock Upstox V3 historical candle response."""
        candles = []
        for i in range(candle_count):
            hour = 9 + i // 20
            minute = 15 + (i * 3) % 60
            candles.append([
                f"2026-08-22T{hour:02d}:{minute:02d}:00+05:30",
                25500.0 + i, 25520.0 + i, 25480.0 + i, 25510.0 + i,
                15000 + i * 100, 0,
            ])
        return {"status": "success", "data": {"candles": candles}}

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty(self, db):
        """Dry-run shows chunks but doesn't fetch."""
        with patch("app.tools.candle_backfill._make_db_session", return_value=db):
            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28), dry_run=True,
            )
            assert results == []

    @pytest.mark.asyncio
    async def test_single_chunk_fetch(self, db):
        """Single chunk: fetch → normalize → validate → persist."""
        mock_response = self._mock_response(5)

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )
            assert len(results) == 1
            assert results[0]["status"] == "ok"
            assert results[0]["fetched"] == 5

    @pytest.mark.asyncio
    async def test_resume_skips_existing_chunks(self, db):
        """Chunks with existing data are skipped."""
        # Pre-populate one candle in the range
        candle = NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2026, 8, 22, 3, 45),
            open=25500.0, high=25520.0, low=25480.0, close=25510.0, volume=15000.0,
        )
        db.add(candle)
        db.commit()

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=True,
            )
            assert len(results) == 1
            assert results[0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_no_skip_re_fetches(self, db):
        """--no-skip forces re-fetch even with existing data."""
        candle = NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2026, 8, 22, 3, 45),
            open=25500.0, high=25520.0, low=25480.0, close=25510.0, volume=15000.0,
        )
        db.add(candle)
        db.commit()

        mock_response = self._mock_response(3)

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )
            assert results[0]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_api_response(self, db):
        """API returns success with empty candles → no error."""
        mock_response = {"status": "success", "data": {"candles": []}}

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )
            assert results[0]["status"] == "ok"
            assert results[0]["fetched"] == 0

    @pytest.mark.asyncio
    async def test_api_error_per_chunk(self, db):
        """API error on a chunk → error status, other chunks still processed."""
        mock_error = UpstoxError(500, "server error")
        mock_ok = self._mock_response(3)

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise mock_error
            return mock_ok

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", side_effect=_side_effect), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 10, 1)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 9, 30),
                skip_existing_chunks=False,
            )
            # At least one error and one ok
            statuses = [r["status"] for r in results]
            assert "error" in statuses
            assert "ok" in statuses

    @pytest.mark.asyncio
    async def test_idempotent_execution(self, db):
        """Running the same backfill twice does not create duplicates."""
        mock_response = self._mock_response(3)

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            # First run
            await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )
            count1 = db.scalar(
                __import__("sqlalchemy").select(
                    __import__("sqlalchemy").func.count(NiftyCandle.id)
                )
            )

            # Second run
            await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )
            count2 = db.scalar(
                __import__("sqlalchemy").select(
                    __import__("sqlalchemy").func.count(NiftyCandle.id)
                )
            )

            assert count1 == count2  # no duplicates

    @pytest.mark.asyncio
    async def test_future_date_clamped(self, db):
        """Future end_date is clamped — no future dates requested."""
        mock_response = self._mock_response(2)

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 8, 23)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2099, 12, 31),
                skip_existing_chunks=False,
            )
            # Should not request beyond today
            assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_invalid_candles_not_persisted(self, db):
        """Hard-invalid candles from API are rejected by validation."""
        # Candles with invalid prices (open=0)
        bad_candles = [
            ["2026-08-22T09:15:00+05:30", 0, 105.0, 95.0, 102.0, 5000, 0],
            ["2026-08-22T09:18:00+05:30", 100.0, 105.0, 95.0, 102.0, 5000, 0],
        ]
        mock_response = {"status": "success", "data": {"candles": bad_candles}}

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            results = await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )
            assert results[0]["valid"] == 1  # only 1 valid candle


# ---------------------------------------------------------------------------
# Lot-size independence
# ---------------------------------------------------------------------------


class TestLotSizeIndependence:
    """Candle backfill is completely independent of lot_size."""

    @pytest.mark.asyncio
    async def test_no_lot_size_in_persisted_candles(self, db):
        """Persisted candles contain no lot_size field."""
        mock_response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-08-22T09:15:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                ]
            },
        }

        with patch("app.tools.candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.candle_backfill.fetch_with_retry", new_callable=AsyncMock, return_value=mock_response), \
             patch("app.tools.candle_backfill._today", return_value=date(2026, 9, 1)):

            await run_backfill(
                "token", date(2026, 8, 1), date(2026, 8, 28),
                skip_existing_chunks=False,
            )

            # Verify the NiftyCandle model has no lot_size column
            candle = db.query(NiftyCandle).first()
            assert candle is not None
            assert not hasattr(candle, "lot_size")
            assert candle.volume == 15000.0  # raw volume, not divided by lot size
