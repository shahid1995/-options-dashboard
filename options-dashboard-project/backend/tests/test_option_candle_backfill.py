"""Phase 7.14 -- Synthetic tests for the option candle backfill engine.

Tests the planner, chunking, checkpoint/resume, rate limiting, retry,
and progress tracking using mocked API responses.  No live API calls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ContractSpec, OptionCandle
from app.services.contract_metadata import upsert_contract_spec, SOURCE_UPSTOX_EXPIRED
from app.services.option_candles import record_option_candles, count_option_candles


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
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# Synthetic contract specs
CONTRACTS = [
    {
        "instrument_key": f"NSE_FO|{48890 + i}|31-10-2024",
        "underlying_symbol": "NIFTY",
        "underlying_key": "NSE_INDEX|Nifty 50",
        "expiry": "2024-10-31",
        "strike_price": 22000.0 + i * 250,
        "instrument_type": "CE" if i % 2 == 0 else "PE",
        "lot_size": 25,
        "minimum_lot": 25,
        "freeze_quantity": 1800,
        "tick_size": 5.0,
        "trading_symbol": f"NIFTY {22000 + i * 250} {'CE' if i % 2 == 0 else 'PE'} 31 OCT 24",
        "segment": "NSE_FO",
        "exchange": "NSE",
        "weekly": False,
        "source": "UPSTOX_EXPIRED",
        "source_reference": f"EXPIRED_INSTRUMENTS/NIFTY/2024-10-31/{i}",
        "fetched_at": datetime.now(timezone.utc),
    }
    for i in range(4)
]


def _mock_candle_response(count: int = 5) -> dict:
    """Create a mock Upstox expired historical candle API response."""
    candles = []
    base_time = datetime(2024, 10, 31, 3, 45)
    for i in range(count):
        ts = base_time + timedelta(minutes=i * 3)
        candles.append([
            f"{ts.strftime('%Y-%m-%dT%H:%M:%S')}+05:30",
            100.0 + i, 105.0 + i, 95.0 + i, 102.0 + i,
            1000 + i * 100, 50000 + i * 1000,
        ])
    return {"status": "success", "data": {"candles": candles}}


def _mock_empty_response() -> dict:
    return {"status": "success", "data": {"candles": []}}


def _mock_error_response() -> dict:
    return {"status": "error", "errors": [{"message": "rate limit exceeded"}]}


# ---------------------------------------------------------------------------
# Contract discovery tests
# ---------------------------------------------------------------------------

class TestDiscoverContracts:
    def test_discover_all(self, db):
        """Discover all contracts in the registry."""
        from app.tools.option_candle_backfill import discover_contracts

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        contracts = discover_contracts(db)
        assert len(contracts) == 4
        assert all(c["instrument_key"].startswith("NSE_FO|") for c in contracts)

    def test_discover_by_expiry(self, db):
        """Filter contracts by expiry."""
        from app.tools.option_candle_backfill import discover_contracts

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        contracts = discover_contracts(db, expiry="2024-10-31")
        assert len(contracts) == 4

    def test_discover_empty(self, db):
        """No contracts in registry returns empty list."""
        from app.tools.option_candle_backfill import discover_contracts

        contracts = discover_contracts(db)
        assert contracts == []


# ---------------------------------------------------------------------------
# Checkpoint / resume tests
# ---------------------------------------------------------------------------

class TestCheckpoint:
    def test_completed_instruments(self, db):
        """Identify contracts that already have candle data."""
        from app.tools.option_candle_backfill import get_completed_instruments

        # Insert candles for 2 of 4 contracts
        for i in range(2):
            record_option_candles(db, [{
                "instrument_key": f"CONTRACT_{i}",
                "interval": "3min",
                "openTime": "2024-10-31T03:45:00Z",
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
                "volume": 1000.0, "open_interest": 50000.0,
            }])

        completed = get_completed_instruments(db)
        assert "CONTRACT_0" in completed
        assert "CONTRACT_1" in completed
        assert "CONTRACT_2" not in completed

    def test_resume_skips_completed(self, db):
        """Backfill skips contracts that already have data."""
        from app.tools.option_candle_backfill import discover_contracts, get_completed_instruments

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        # Mark first 2 as completed
        for c in CONTRACTS[:2]:
            record_option_candles(db, [{
                "instrument_key": c["instrument_key"],
                "interval": "3min",
                "openTime": "2024-10-31T03:45:00Z",
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
                "volume": 1000.0, "open_interest": 50000.0,
            }])

        all_contracts = discover_contracts(db)
        completed = get_completed_instruments(db)
        remaining = [c for c in all_contracts if c["instrument_key"] not in completed]

        assert len(all_contracts) == 4
        assert len(remaining) == 2
        assert all(c["instrument_key"].startswith("NSE_FO|48892") or c["instrument_key"].startswith("NSE_FO|48893") for c in remaining)


# ---------------------------------------------------------------------------
# Backfill contract tests (mocked API)
# ---------------------------------------------------------------------------

class TestBackfillContract:
    @pytest.mark.asyncio
    async def test_successful_backfill(self, db):
        """Successfully fetch and persist candles for one contract."""
        from app.tools.option_candle_backfill import backfill_contract

        upsert_contract_spec(db, CONTRACTS[0], source=SOURCE_UPSTOX_EXPIRED)

        with patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(3)):
            result = await backfill_contract(db, "test-token", CONTRACTS[0])

        assert result["status"] == "ok"
        assert result["candles_fetched"] == 3
        assert result["candles_persisted"] == 3

        # Verify data in DB
        count = count_option_candles(db, CONTRACTS[0]["instrument_key"])
        assert count == 3

    @pytest.mark.asyncio
    async def test_empty_response(self, db):
        """Empty API response results in 'empty' status."""
        from app.tools.option_candle_backfill import backfill_contract

        with patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_empty_response()):
            result = await backfill_contract(db, "test-token", CONTRACTS[0])

        assert result["status"] == "empty"
        assert result["candles_fetched"] == 0

    @pytest.mark.asyncio
    async def test_api_error(self, db):
        """API error results in 'error' status."""
        from app.tools.option_candle_backfill import backfill_contract
        from app.services.upstox import UpstoxError

        with patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, side_effect=UpstoxError(429, "rate limit")):
            result = await backfill_contract(db, "test-token", CONTRACTS[0])

        assert result["status"] == "error"
        assert "429" in result["error"]

    @pytest.mark.asyncio
    async def test_dry_run(self, db):
        """Dry run does not make API calls."""
        from app.tools.option_candle_backfill import backfill_contract

        with patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock) as mock_fetch:
            result = await backfill_contract(db, "test-token", CONTRACTS[0], dry_run=True)

        assert result["status"] == "dry_run"
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_persistence(self, db):
        """Running the same backfill twice does not create duplicates."""
        from app.tools.option_candle_backfill import backfill_contract

        with patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(3)):
            r1 = await backfill_contract(db, "test-token", CONTRACTS[0])
            r2 = await backfill_contract(db, "test-token", CONTRACTS[0])

        assert r1["candles_persisted"] == 3
        assert r2["candles_persisted"] == 3
        # But no duplicates in DB
        count = count_option_candles(db, CONTRACTS[0]["instrument_key"])
        assert count == 3


# ---------------------------------------------------------------------------
# Run backfill tests (mocked)
# ---------------------------------------------------------------------------

class TestRunBackfill:
    @pytest.mark.asyncio
    async def test_full_backfill(self, db):
        """Full backfill processes all contracts."""
        from app.tools.option_candle_backfill import run_backfill

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(2)):

            # Mock time.sleep to avoid delays in tests
            with patch("app.tools.option_candle_backfill.time.sleep"):
                stats = await run_backfill(
                    "test-token",
                    expiry="2024-10-31",
                    dry_run=False,
                    skip_existing=False,
                )

        assert stats["contracts_discovered"] == 4
        assert stats["contracts_fetched"] == 4
        assert stats["total_candles_persisted"] == 8  # 4 contracts × 2 candles

    @pytest.mark.asyncio
    async def test_dry_run(self, db):
        """Dry run shows contracts without fetching."""
        from app.tools.option_candle_backfill import run_backfill

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db):
            stats = await run_backfill("test-token", expiry="2024-10-31", dry_run=True)

        assert stats["contracts_discovered"] == 4
        assert stats["contracts_fetched"] == 0

    @pytest.mark.asyncio
    async def test_skip_existing(self, db):
        """Already-fetched contracts are skipped."""
        from app.tools.option_candle_backfill import run_backfill

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        # Pre-populate 2 contracts with candle data
        for c in CONTRACTS[:2]:
            record_option_candles(db, [{
                "instrument_key": c["instrument_key"],
                "interval": "3min",
                "openTime": "2024-10-31T03:45:00Z",
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
                "volume": 1000.0, "open_interest": 50000.0,
            }])

        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(1)), \
             patch("app.tools.option_candle_backfill.time.sleep"):
            stats = await run_backfill("test-token", expiry="2024-10-31", skip_existing=True)

        assert stats["contracts_discovered"] == 4
        assert stats["contracts_skipped"] == 2
        assert stats["contracts_fetched"] == 2  # only remaining 2

    @pytest.mark.asyncio
    async def test_max_contracts(self, db):
        """Limit the number of contracts processed."""
        from app.tools.option_candle_backfill import run_backfill

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(1)), \
             patch("app.tools.option_candle_backfill.time.sleep"):
            stats = await run_backfill("test-token", expiry="2024-10-31", max_contracts=2)

        assert stats["contracts_fetched"] <= 2

    @pytest.mark.asyncio
    async def test_error_handling(self, db):
        """Errors on individual contracts don't stop the backfill."""
        from app.tools.option_candle_backfill import run_backfill
        from app.services.upstox import UpstoxError

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        call_count = 0
        async def mock_fetch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise UpstoxError(401, "unauthorized")  # non-retryable
            return _mock_candle_response(1)

        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    side_effect=mock_fetch), \
             patch("app.tools.option_candle_backfill.time.sleep"):
            stats = await run_backfill("test-token", expiry="2024-10-31", skip_existing=False)

        assert stats["contracts_error"] >= 1
        assert stats["contracts_fetched"] >= 1  # at least one succeeded


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_delay_between_requests(self, db):
        """Backfill respects rate-limit delay between contracts."""
        from app.tools.option_candle_backfill import run_backfill, REQUEST_DELAY_SECONDS

        for c in CONTRACTS[:2]:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        sleep_calls = []
        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(1)), \
             patch("app.tools.option_candle_backfill.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            await run_backfill("test-token", expiry="2024-10-31", skip_existing=False)

        # Should have slept between contracts (not after the last one)
        assert len(sleep_calls) >= 1
        assert all(s >= REQUEST_DELAY_SECONDS for s in sleep_calls)


# ---------------------------------------------------------------------------
# Progress tracking tests
# ---------------------------------------------------------------------------

class TestProgressTracking:
    @pytest.mark.asyncio
    async def test_progress_increments(self, db):
        """Progress tracking shows incremental improvement."""
        from app.tools.option_candle_backfill import run_backfill, get_completed_instruments

        for c in CONTRACTS:
            upsert_contract_spec(db, c, source=SOURCE_UPSTOX_EXPIRED)

        # Initially no progress
        completed = get_completed_instruments(db)
        assert len(completed) == 0

        # Backfill 2 contracts
        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(1)), \
             patch("app.tools.option_candle_backfill.time.sleep"):
            await run_backfill("test-token", expiry="2024-10-31", max_contracts=2)

        completed = get_completed_instruments(db)
        assert len(completed) == 2

        # Backfill remaining
        with patch("app.tools.option_candle_backfill._make_db_session", return_value=db), \
             patch("app.tools.option_candle_backfill.get_expired_historical_candles",
                    new_callable=AsyncMock, return_value=_mock_candle_response(1)), \
             patch("app.tools.option_candle_backfill.time.sleep"):
            await run_backfill("test-token", expiry="2024-10-31", skip_existing=True)

        completed = get_completed_instruments(db)
        assert len(completed) == 4
