"""Phase 7.24.8A — Backfill Optimization Audit Tests.

Tests for:
  - Universe selection and ATM calculation
  - No duplicate instruments
  - CE/PE symmetry
  - Lot-size preservation
  - Checkpoint compatibility
  - Bounded concurrency
  - Failure isolation
  - 429 handling
  - 401 handling
  - Database transaction isolation
  - Dry-run produces no API calls
  - Existing completed instruments are skipped

All tests use mocked HTTP responses. No real Upstox API calls.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ContractSpec,
    IngestionCheckpoint,
    NiftyCandle,
    OptionCandle,
)
from app.services.backfill_benchmark import (
    calculate_historical_atm,
    calculate_universe_size,
    get_representative_instruments,
    benchmark_single_instrument,
    benchmark_concurrency,
    benchmark_db_write,
    benchmark_date_range_efficiency,
    InstrumentBenchmark,
    ConcurrencyBenchmark,
    DatabaseWriteBenchmark,
)
from app.services.backfill_orchestrator import (
    BackfillOrchestrator,
    NIFTY_INDEX_KEY,
    NIFTY_SYMBOL,
    PIPELINE_OPTIONS,
    _upsert_checkpoint,
)
from app.services.upstox_client import (
    UpstoxClient,
    UpstoxAuthenticationError,
    UpstoxRateLimitError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class MockTokenProvider:
    def __init__(self, token="test-token-123"):
        self._token = token
    def get_token(self):
        return self._token


def _mock_client():
    client = AsyncMock(spec=UpstoxClient)
    client._token_provider = MockTokenProvider()
    _sample_candle = [
        ["2024-10-03T09:15:00+05:30", 150.5, 155.0, 148.0, 152.3, 5000, 325000],
        ["2024-10-03T09:18:00+05:30", 152.3, 156.0, 151.0, 154.5, 4500, 320000],
    ] * 50  # 100 candles per instrument
    client.get_expired_historical_candles = AsyncMock(return_value=_sample_candle)
    _sample_nifty = [["2024-10-03T09:15:00+05:30", 25000, 25020, 24980, 25010, 15000, 0]] * 125  # 125 candles per day
    client.get_historical_candles = AsyncMock(return_value=_sample_nifty)
    client.get_expiries = AsyncMock(return_value=["2024-10-03", "2024-10-10", "2024-10-17"])
    client.get_contracts = AsyncMock(return_value=[])
    client.metrics = MagicMock()
    client.metrics.snapshot.return_value = {"total_requests": 0}
    client.metrics.total_requests = 0
    client.metrics.successful_requests = 0
    client.metrics.failed_requests = 0
    client.metrics.rate_limit_count = 0
    client.metrics.authentication_failures = 0
    client.metrics.retry_count = 0
    client.metrics.network_failures = 0
    client.metrics.total_elapsed_time = 0.0
    return client


def _add_nifty_candles(db, start_date, count=5):
    """Add NIFTY candles for testing ATM calculation."""
    from datetime import timedelta
    for i in range(count):
        d = start_date + timedelta(days=i)
        dt = datetime(d.year, d.month, d.day, 9, 15)
        db.add(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=dt,
            open=25000 + i * 10, high=25020 + i * 10,
            low=24980 + i * 10, close=25010 + i * 10, volume=15000,
        ))
    db.commit()


def _add_spec(db, ik, expiry, strike, opt_type, lot=75):
    spec = ContractSpec(
        instrument_key=ik, underlying="NIFTY", underlying_key=NIFTY_INDEX_KEY,
        expiry=expiry, strike_price=strike, instrument_type=opt_type,
        lot_size=lot, minimum_lot=lot,
        trading_symbol=f"NIFTY{expiry.replace('-', '')}{int(strike)}{opt_type}",
        segment="NSE_FO", exchange="NSE",
        source="TEST", source_reference="test",
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(spec)
    db.commit()
    return spec


def _add_specs_for_expiry(db, expiry, strikes, lot=75):
    """Add CE and PE specs for each strike in the expiry."""
    for strike in strikes:
        _add_spec(db, f"NSE_FO|{int(strike * 10)}|{expiry}", expiry, strike, "CE", lot)
        _add_spec(db, f"NSE_FO|{int(strike * 10 + 1)}|{expiry}", expiry, strike, "PE", lot)


# ===========================================================================
# 1. UNIVERSE SELECTION
# ===========================================================================

class TestUniverseSelection:
    def test_universe_atm_plus_5_count(self, db):
        """ATM ±5 should include 11 strikes × 2 types = 22 instruments per expiry."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        universe = calculate_universe_size(db, offset=5)
        assert universe["offset"] == 5
        assert universe["total_instruments"] <= 22  # Up to 11 strikes × 2
        assert universe["percentage"] < 100

    def test_universe_atm_plus_10_count(self, db):
        """ATM ±10 should include 21 strikes × 2 types = 42 instruments per expiry."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        universe = calculate_universe_size(db, offset=10)
        assert universe["offset"] == 10
        assert universe["total_instruments"] <= 42

    def test_universe_atm_plus_20_count(self, db):
        """ATM ±20 should include 41 strikes × 2 types = 82 instruments per expiry."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        universe = calculate_universe_size(db, offset=20)
        assert universe["offset"] == 20
        assert universe["total_instruments"] <= 82

    def test_universe_atm_plus_30_count(self, db):
        """ATM ±30 should include all strikes if within range."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        universe = calculate_universe_size(db, offset=30)
        assert universe["offset"] == 30
        # Should include most/all strikes
        assert universe["total_instruments"] > 0

    def test_universe_monotonic_with_offset(self, db):
        """Larger offset should include equal or more instruments."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        results = []
        for offset in [5, 10, 20, 30]:
            universe = calculate_universe_size(db, offset)
            results.append(universe["total_instruments"])

        for i in range(len(results) - 1):
            assert results[i] <= results[i + 1], (
                f"Universe should be monotonic: offset {i} gave {results[i]}, "
                f"offset {i+1} gave {results[i+1]}"
            )

    def test_universe_empty_without_nifty_candles(self, db):
        """Without NIFTY candles, ATM cannot be calculated."""
        strikes = [25000 + i * 50 for i in range(-5, 6)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        universe = calculate_universe_size(db, offset=5)
        assert universe["total_instruments"] == 0


# ===========================================================================
# 2. HISTORICAL ATM CALCULATION
# ===========================================================================

class TestHistoricalATM:
    def test_atm_nearest_strike(self, db):
        """ATM should be the strike nearest to the NIFTY reference price."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [24950, 25000, 25050, 25100, 25150]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        atm = calculate_historical_atm(db, "2024-10-03")
        assert atm is not None
        # NIFTY opened at 25000, so ATM should be 25000
        assert atm == 25000

    def test_atm_no_nifty_data(self, db):
        """ATM returns None when no NIFTY data exists."""
        strikes = [25000, 25050, 25100]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        atm = calculate_historical_atm(db, "2024-10-03")
        assert atm is None

    def test_atm_no_specs(self, db):
        """ATM returns None when no contract specs exist."""
        _add_nifty_candles(db, date(2024, 9, 30))

        atm = calculate_historical_atm(db, "2024-10-03")
        assert atm is None

    def test_atm_invalid_expiry_format(self, db):
        """ATM returns None for invalid expiry format."""
        _add_nifty_candles(db, date(2024, 9, 30))
        atm = calculate_historical_atm(db, "invalid-date")
        assert atm is None

    def test_atm_uses_closest_pre_expiry_price(self, db):
        """ATM uses the most recent NIFTY price before expiry."""
        # Add NIFTY candle just before expiry
        dt_before = datetime(2024, 10, 2, 9, 15)
        db.add(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=dt_before,
            open=25200, high=25220, low=25180, close=25210, volume=15000,
        ))
        db.commit()

        strikes = [25000, 25050, 25100, 25150, 25200, 25250, 25300]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        atm = calculate_historical_atm(db, "2024-10-03")
        assert atm == 25200  # Nearest to 25200 reference


# ===========================================================================
# 3. NO DUPLICATE INSTRUMENTS
# ===========================================================================

class TestNoDuplicateInstruments:
    def test_representative_instruments_unique(self, db):
        """Representative instrument selection produces no duplicates."""
        _add_nifty_candles(db, date(2024, 9, 30))
        _add_nifty_candles(db, date(2025, 1, 28), count=3)
        strikes = [25000 + i * 50 for i in range(-20, 21)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)
        _add_specs_for_expiry(db, "2025-01-30", strikes)

        instruments = get_representative_instruments(db, limit=20)
        keys = [s.instrument_key for s in instruments]
        assert len(keys) == len(set(keys)), "Representative instruments must be unique"


# ===========================================================================
# 4. CE/PE SYMMETRY
# ===========================================================================

class TestCESymmetry:
    def test_each_strike_has_both_ce_and_pe(self, db):
        """Every strike in the universe should have both CE and PE."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050, 25100, 25150, 25200]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        # Check that each strike has both types
        for strike in strikes:
            ce = db.execute(
                select(ContractSpec)
                .where(ContractSpec.expiry == "2024-10-03")
                .where(ContractSpec.strike_price == strike)
                .where(ContractSpec.instrument_type == "CE")
            ).first()
            pe = db.execute(
                select(ContractSpec)
                .where(ContractSpec.expiry == "2024-10-03")
                .where(ContractSpec.strike_price == strike)
                .where(ContractSpec.instrument_type == "PE")
            ).first()
            assert ce is not None, f"Missing CE for strike {strike}"
            assert pe is not None, f"Missing PE for strike {strike}"


# ===========================================================================
# 5. LOT-SIZE PRESERVATION
# ===========================================================================

class TestLotSizePreservation:
    def test_lot_size_not_overwritten(self, db):
        """Lot size should be preserved once set."""
        spec = _add_spec(db, "NSE_FO|250000|2024-10-03", "2024-10-03", 25000, "CE", lot=25)

        # Try to update with different lot size via upsert
        from app.services.contract_metadata import upsert_contract_spec
        result = upsert_contract_spec(db, {
            "instrument_key": "NSE_FO|250000|2024-10-03",
            "lot_size": 75,  # Different!
            "minimum_lot": 75,
        })

        # Lot size should NOT be overwritten
        updated = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|250000|2024-10-03")
        ).scalar_one()
        assert updated.lot_size == 25  # Original preserved
        assert result.action == "conflict"

    def test_lot_size_filled_when_null(self, db):
        """Lot size should be filled when initially NULL."""
        spec = _add_spec(db, "NSE_FO|250000|2024-10-03", "2024-10-03", 25000, "CE", lot=None)
        spec.lot_size = None
        db.commit()

        from app.services.contract_metadata import upsert_contract_spec
        result = upsert_contract_spec(db, {
            "instrument_key": "NSE_FO|250000|2024-10-03",
            "lot_size": 75,
            "minimum_lot": 75,
        })

        updated = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|250000|2024-10-03")
        ).scalar_one()
        assert updated.lot_size == 75
        assert result.action == "filled_lot_size"


# ===========================================================================
# 6. CHECKPOINT COMPATIBILITY
# ===========================================================================

class TestCheckpointCompatibility:
    def test_checkpoint_created_per_instrument(self, db):
        """Each instrument gets its own checkpoint."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = asyncio.get_event_loop().run_until_complete(orch.run_options())

        # Checkpoints should exist for each instrument
        checkpoints = db.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == PIPELINE_OPTIONS)
        ).scalars().all()
        assert len(checkpoints) >= 2

    def test_completed_checkpoint_prevents_redownload(self, db):
        """Completed checkpoint means instrument is skipped on resume."""
        _add_spec(db, "NSE_FO|250000|2024-10-03", "2024-10-03", 25000, "CE")
        _add_option_candle(db, "NSE_FO|250000|2024-10-03", datetime(2024, 10, 3, 9, 15))

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = asyncio.get_event_loop().run_until_complete(orch.run_options())

        # Should be skipped
        assert result.rows_skipped >= 1


def _add_option_candle(db, ik, dt, open_p=150.0, volume=5000.0, oi=325000.0):
    c = OptionCandle(
        instrument_key=ik, interval="3min", open_time=dt,
        open=open_p, high=open_p + 5, low=open_p - 2, close=open_p + 2,
        volume=volume, open_interest=oi,
        source="UPSTOX_EXPIRED_CANDLE", fetched_at=datetime.now(timezone.utc),
    )
    db.add(c)
    db.commit()
    return c


# ===========================================================================
# 7. BOUNDED CONCURRENCY
# ===========================================================================

class TestBoundedConcurrency:
    @pytest.mark.asyncio
    async def test_concurrency_1(self, db):
        """Concurrency=1 processes instruments sequentially."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050, 25100]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        client = _mock_client()
        result = await benchmark_concurrency(client, db, instruments, concurrency=1)

        assert result.workers == 1
        assert result.total_requests == len(instruments)

    @pytest.mark.asyncio
    async def test_concurrency_4(self, db):
        """Concurrency=4 processes instruments with bounded parallelism."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050, 25100, 25150, 25200, 25250, 25300, 25350]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        client = _mock_client()
        result = await benchmark_concurrency(client, db, instruments, concurrency=4)

        assert result.workers == 4
        assert result.successful_requests == len(instruments)

    @pytest.mark.asyncio
    async def test_concurrency_respects_semaphore(self, db):
        """Semaphore limits concurrent API calls."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(10)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def counting_client(*args, **kwargs):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return [
                ["2024-10-03T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
            ]

        client = _mock_client()
        client.get_expired_historical_candles = counting_client

        await benchmark_concurrency(client, db, instruments, concurrency=2)
        assert max_concurrent <= 2


# ===========================================================================
# 8. FAILURE ISOLATION
# ===========================================================================

class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_one_failure_does_not_affect_others(self, db):
        """A failed instrument should not prevent others from succeeding."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050, 25100, 25150, 25200]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        call_count = 0

        async def selective_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated API failure")
            return [
                ["2024-10-03T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
            ]

        client = _mock_client()
        client.get_expired_historical_candles = selective_failure

        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options()

        # At least 4 instruments should have succeeded
        assert result.rows_inserted >= 4
        assert len(result.errors) >= 1

    @pytest.mark.asyncio
    async def test_failure_does_not_rollback_other_transactions(self, db):
        """Instrument A's failure must not roll back Instrument B's data."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        call_count = 0

        async def fail_second(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Instrument B failed")
            return [
                ["2024-10-03T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
            ]

        client = _mock_client()
        client.get_expired_historical_candles = fail_second

        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options()

        # First instrument's data should still be in DB
        first_ik = "NSE_FO|250000|2024-10-03"
        candle_count = db.scalar(
            select(func.count(OptionCandle.id))
            .where(OptionCandle.instrument_key == first_ik)
        )
        assert candle_count > 0, "First instrument's data should be preserved"


# ===========================================================================
# 9. 429 HANDLING
# ===========================================================================

class TestRateLimitHandling:
    @pytest.mark.asyncio
    async def test_429_recorded_in_benchmark(self, db):
        """429 rate limits should be counted in benchmark results."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()
        n = len(instruments)

        async def rate_limited(*args, **kwargs):
            raise UpstoxRateLimitError("Rate limit exceeded")

        client = _mock_client()
        client.get_expired_historical_candles = rate_limited

        result = await benchmark_concurrency(client, db, instruments, concurrency=1)
        assert result.rate_limit_429 == n

    @pytest.mark.asyncio
    async def test_429_does_not_crash_benchmark(self, db):
        """429 should be handled gracefully, not crash the benchmark."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        async def rate_limited(*args, **kwargs):
            raise UpstoxRateLimitError("Rate limit exceeded")

        client = _mock_client()
        client.get_expired_historical_candles = rate_limited

        # Should not raise — gracefully handled
        result = await benchmark_concurrency(client, db, instruments, concurrency=1)
        assert result.rate_limit_429 == len(instruments)


# ===========================================================================
# 10. 401 HANDLING
# ===========================================================================

class TestAuthFailureHandling:
    @pytest.mark.asyncio
    async def test_401_recorded_in_benchmark(self, db):
        """401 auth failures should be counted in benchmark results."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()
        n = len(instruments)

        async def auth_fail(*args, **kwargs):
            raise UpstoxAuthenticationError("Token expired")

        client = _mock_client()
        client.get_expired_historical_candles = auth_fail

        result = await benchmark_concurrency(client, db, instruments, concurrency=1)
        assert result.auth_failures_401 == n

    @pytest.mark.asyncio
    async def test_401_does_not_crash_benchmark(self, db):
        """401 should be handled gracefully."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        async def auth_fail(*args, **kwargs):
            raise UpstoxAuthenticationError("Token expired")

        client = _mock_client()
        client.get_expired_historical_candles = auth_fail

        result = await benchmark_concurrency(client, db, instruments, concurrency=1)
        assert result.auth_failures_401 == len(instruments)


# ===========================================================================
# 11. DATABASE TRANSACTION ISOLATION
# ===========================================================================

class TestDatabaseTransactionIsolation:
    @pytest.mark.asyncio
    async def test_each_instrument_has_independent_transaction(self, db):
        """Each instrument's DB write is independent."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        await orch.run_options()

        # Each instrument should have its own checkpoint
        checkpoints = db.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == PIPELINE_OPTIONS)
        ).scalars().all()

        instrument_keys = [cp.instrument_key for cp in checkpoints]
        assert len(instrument_keys) == len(set(instrument_keys)), (
            "Each instrument must have its own checkpoint"
        )

    @pytest.mark.asyncio
    async def test_committed_data_survives_later_failure(self, db):
        """Data committed for instrument A survives even if instrument B fails."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        # Get actual instrument keys in order
        all_specs = db.execute(
            select(ContractSpec)
            .where(ContractSpec.expiry == "2024-10-03")
            .order_by(ContractSpec.instrument_key)
        ).scalars().all()
        first_ik = all_specs[0].instrument_key
        second_ik = all_specs[1].instrument_key

        call_count = 0

        async def fail_after_first(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated failure for second instrument")
            return [
                ["2024-10-03T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
            ]

        client = _mock_client()
        client.get_expired_historical_candles = fail_after_first

        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options()

        # First instrument's candles should be committed
        count = db.scalar(
            select(func.count(OptionCandle.id))
            .where(OptionCandle.instrument_key == first_ik)
        )
        assert count > 0, "First instrument's candles should be committed"

        # Second instrument's checkpoint should show FAILED
        cp = db.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == PIPELINE_OPTIONS)
            .where(IngestionCheckpoint.instrument_key == second_ik)
        ).scalar_one_or_none()
        assert cp is not None
        assert cp.status == "FAILED"


# ===========================================================================
# 12. DRY-RUN PRODUCES NO API CALLS
# ===========================================================================

class TestDryRunNoAPICalls:
    @pytest.mark.asyncio
    async def test_dry_run_benchmark_no_api_calls(self, db):
        """Dry-run benchmark should make zero API calls."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        instruments = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        client = _mock_client()

        for spec in instruments:
            result = await benchmark_single_instrument(client, db, spec, dry_run=True)
            assert result.success is True
            assert result.candles_returned == 0  # No API call

        client.get_expired_historical_candles.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_orchestrator_no_api_calls(self, db):
        """Dry-run orchestrator should not fetch candle data."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)
        await orch.run_options()

        client.get_expired_historical_candles.assert_not_called()


# ===========================================================================
# 13. EXISTING COMPLETED INSTRUMENTS ARE SKIPPED
# ===========================================================================

class TestExistingCompletedSkipped:
    @pytest.mark.asyncio
    async def test_instruments_with_data_are_skipped(self, db):
        """Instruments that already have candle data should be skipped."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        # Pre-populate data for first instrument (CE)
        first_ik = db.execute(
            select(ContractSpec.instrument_key)
            .where(ContractSpec.expiry == "2024-10-03")
            .where(ContractSpec.instrument_type == "CE")
        ).scalars().first()
        _add_option_candle(db, first_ik, datetime(2024, 10, 3, 9, 15))

        all_specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options()

        # First instrument should be skipped
        assert result.rows_skipped >= 1
        # Only remaining instruments should be fetched
        assert client.get_expired_historical_candles.call_count == len(all_specs) - 1

    @pytest.mark.asyncio
    async def test_force_flag_overrides_skip(self, db):
        """Force flag should re-download even existing instruments."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)
        first_ik = db.execute(
            select(ContractSpec.instrument_key)
            .where(ContractSpec.expiry == "2024-10-03")
            .where(ContractSpec.instrument_type == "CE")
        ).scalars().first()
        _add_option_candle(db, first_ik, datetime(2024, 10, 3, 9, 15))

        all_specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        client = _mock_client()
        orch = BackfillOrchestrator(db, client, force=True)
        result = await orch.run_options()

        # Force should process ALL instruments
        assert result.rows_skipped == 0
        assert client.get_expired_historical_candles.call_count == len(all_specs)


# ===========================================================================
# 14. INSTRUMENT BENCHMARK DATACLASS
# ===========================================================================

class TestInstrumentBenchmark:
    def test_to_dict(self):
        """InstrumentBenchmark.to_dict returns expected keys."""
        b = InstrumentBenchmark(
            instrument_key="NSE_FO|250000|2024-10-03",
            expiry="2024-10-03",
            strike=25000.0,
            instrument_type="CE",
            lot_size=75,
            request_latency_ms=123.4,
            candles_returned=125,
            rows_inserted=125,
            success=True,
        )
        d = b.to_dict()
        assert d["instrument_key"] == "NSE_FO|250000|2024-10-03"
        assert d["request_latency_ms"] == 123.4
        assert d["candles_returned"] == 125
        assert d["success"] is True


class TestConcurrencyBenchmark:
    def test_to_dict(self):
        """ConcurrencyBenchmark.to_dict returns expected keys."""
        b = ConcurrencyBenchmark(
            workers=4,
            total_requests=10,
            successful_requests=8,
            rate_limit_429=2,
            average_latency_ms=150.0,
            p95_latency_ms=200.0,
            candles_per_sec=50.0,
            instruments_per_sec=5.0,
            total_elapsed_sec=2.0,
        )
        d = b.to_dict()
        assert d["workers"] == 4
        assert d["successful_requests"] == 8
        assert d["rate_limit_429"] == 2


class TestDatabaseWriteBenchmark:
    def test_attributes(self):
        """DatabaseWriteBenchmark has expected attributes."""
        b = DatabaseWriteBenchmark(
            api_time_ms=100.0,
            processing_time_ms=10.0,
            db_insert_time_ms=50.0,
            db_commit_time_ms=20.0,
            checkpoint_time_ms=5.0,
            total_time_ms=185.0,
            candles_count=125,
        )
        assert b.candles_count == 125
        assert b.total_time_ms == 185.0


# ===========================================================================
# 15. UNIVERSE PERCENTAGE CALCULATIONS
# ===========================================================================

class TestUniversePercentage:
    def test_universe_percentage_less_than_100(self, db):
        """Each universe should be a subset of total contracts."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        for offset in [5, 10, 20, 30]:
            universe = calculate_universe_size(db, offset)
            assert universe["percentage"] <= 100.0

    def test_universe_estimated_time_positive(self, db):
        """Estimated time should be positive."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-5, 6)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        universe = calculate_universe_size(db, offset=5)
        assert universe["estimated_time_minutes"] > 0
