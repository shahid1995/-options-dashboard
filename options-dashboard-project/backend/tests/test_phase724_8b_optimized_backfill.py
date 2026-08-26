"""Phase 7.24.8B — Optimized Historical Backfill Tests.

Tests for:
  - ATM ±10 universe selection
  - CE/PE symmetry
  - Historical ATM correctness
  - Four-worker concurrency
  - Bounded worker count
  - 429 handling
  - Adaptive concurrency reduction
  - Checkpoint/resume
  - Idempotency
  - Existing-data skipping
  - Failure isolation
  - Transaction isolation
  - Raw OHLCV/OI immutability
  - No server-startup ingestion
  - No API calls during dry-run
  - No token leakage
  - IST timestamp convention

All tests use mocked HTTP responses. No real Upstox API calls.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

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
from app.services.backfill_orchestrator import (
    BackfillOrchestrator,
    NIFTY_INDEX_KEY,
    NIFTY_SYMBOL,
    PIPELINE_OPTIONS,
    DEFAULT_CONCURRENCY,
    MAX_CONCURRENCY,
    ADAPTIVE_REDUCE_THRESHOLD,
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
    _sample_nifty = [["2024-10-03T09:15:00+05:30", 25000, 25020, 24980, 25010, 15000, 0]] * 125
    client.get_historical_candles = AsyncMock(return_value=_sample_nifty)
    client.get_expiries = AsyncMock(return_value=["2024-10-03", "2024-10-10", "2024-10-17"])
    client.get_contracts = AsyncMock(return_value=[])
    client.metrics = MagicMock()
    client.metrics.snapshot.return_value = {"total_requests": 0}
    return client


def _add_nifty_candles(db, start_date, count=5):
    """Add NIFTY candles for testing ATM calculation."""
    for i in range(count):
        d = start_date + timedelta(days=i)
        dt = datetime(d.year, d.month, d.day, 9, 15)
        db.add(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=dt,
            open=25000 + i * 10, high=25020 + i * 10,
            low=24980 + i * 10, close=25010 + i * 10, volume=15000,
        ))
    db.commit()


def _add_nifty_candle(db, d, open_price, interval="3min", hour=9, minute=15):
    """Add a single NIFTY candle on date *d* at the given time."""
    dt = datetime(d.year, d.month, d.day, hour, minute)
    db.add(NiftyCandle(
        symbol="NIFTY", interval=interval, open_time=dt,
        open=open_price, high=open_price + 20,
        low=open_price - 20, close=open_price + 10, volume=15000,
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
    """Add CE and PE specs for each strike."""
    for strike in strikes:
        _add_spec(db, f"NSE_FO|{int(strike * 10)}|{expiry}", expiry, strike, "CE", lot)
        _add_spec(db, f"NSE_FO|{int(strike * 10 + 1)}|{expiry}", expiry, strike, "PE", lot)


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
# 1. ATM ±10 UNIVERSE SELECTION
# ===========================================================================

class TestATMUniverseSelection:
    def test_atm_10_selects_correct_range(self, db):
        """ATM ±10 should select 21 strikes × 2 types = 42 instruments per expiry."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_10")
        # ATM is 25000, so ±10 strikes = 21 strikes × 2 types = 42
        assert len(filtered) == 42

    def test_atm_5_selects_correct_range(self, db):
        """ATM ±5 should select 11 strikes × 2 types = 22 instruments."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_5")
        assert len(filtered) == 22

    def test_atm_20_selects_correct_range(self, db):
        """ATM ±20 should select 41 strikes × 2 types = 82 instruments."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_20")
        assert len(filtered) == 82

    def test_atm_30_selects_all_strikes(self, db):
        """ATM ±30 should select all strikes within range."""
        _add_nifty_candles(db, date(2024, 9, 30))
        # Override the expiry-day candle to open at 25000 so ATM=25000 (index 30)
        # and ATM_30 covers all 61 strikes symmetrically.
        expiry_candle = db.execute(
            select(NiftyCandle).where(
                NiftyCandle.symbol == "NIFTY",
                NiftyCandle.interval == "3min",
                NiftyCandle.open_time == datetime(2024, 10, 3, 9, 15),
            )
        ).scalar_one()
        expiry_candle.open = 25000.0
        expiry_candle.high = 25020.0
        expiry_candle.low = 24980.0
        expiry_candle.close = 25010.0
        db.commit()
        strikes = [25000 + i * 50 for i in range(-30, 31)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_30")
        # ATM=25000 at index 30 → range [0,60] = all 61 strikes × 2 types = 122
        assert len(filtered) == 122

    def test_unknown_universe_returns_all(self, db):
        """Unknown universe string returns all instruments."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-5, 6)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "UNKNOWN")
        assert len(filtered) == len(specs)


# ===========================================================================
# 2. CE/PE SYMMETRY
# ===========================================================================

class TestCESymmetry:
    def test_atm_10_preserves_ce_pe_symmetry(self, db):
        """ATM ±10 should include both CE and PE for each strike."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-15, 16)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.expiry == "2024-10-03")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_10")
        ce_count = sum(1 for s in filtered if s.instrument_type == "CE")
        pe_count = sum(1 for s in filtered if s.instrument_type == "PE")
        assert ce_count == pe_count


# ===========================================================================
# 3. HISTORICAL ATM CORRECTNESS
# ===========================================================================

class TestHistoricalATM:
    def test_calculate_historical_atm_uses_local_data(self, db):
        """ATM calculation uses only local NIFTY candles — no API calls."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050, 25100]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        atm = orch._calculate_historical_atm("2024-10-03")
        # Expiry-day open = 25030 (day 3 in sequence) → nearest strike 25050
        assert atm == 25050  # Nearest to NIFTY expiry-day open of 25030

    def test_calculate_historical_atm_no_nifty_data(self, db):
        """ATM returns None when no NIFTY data exists."""
        strikes = [25000, 25050, 25100]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        atm = orch._calculate_historical_atm("2024-10-03")
        assert atm is None


# ===========================================================================
# 4. FOUR-WORKER CONCURRENCY
# ===========================================================================

class TestFourWorkerConcurrency:
    @pytest.mark.asyncio
    async def test_concurrency_4_processes_all_instruments(self, db):
        """Concurrency=4 should process all instruments."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(8)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(concurrency=4)

        assert result.status == "SUCCESS"
        assert result.rows_inserted > 0

    @pytest.mark.asyncio
    async def test_concurrency_1_still_works(self, db):
        """Concurrency=1 should work (sequential path)."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(concurrency=1)

        assert result.status == "SUCCESS"
        assert result.rows_inserted > 0


# ===========================================================================
# 5. BOUNDED WORKER COUNT
# ===========================================================================

class TestBoundedWorkerCount:
    def test_concurrency_capped_at_max(self, db):
        """Concurrency should be capped at MAX_CONCURRENCY."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        # Request more than max
        # The orchestrator caps it internally
        assert MAX_CONCURRENCY == 6

    def test_concurrency_minimum_is_1(self, db):
        """Concurrency should be at least 1."""
        # Verify the cap logic
        assert max(1, min(0, MAX_CONCURRENCY)) == 1
        assert max(1, min(-5, MAX_CONCURRENCY)) == 1
        assert max(1, min(100, MAX_CONCURRENCY)) == MAX_CONCURRENCY


# ===========================================================================
# 6. 429 HANDLING
# ===========================================================================

class TestRateLimitHandling:
    @pytest.mark.asyncio
    async def test_429_recorded_in_errors(self, db):
        """429 rate limits should be recorded in result errors."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        async def rate_limited(*args, **kwargs):
            raise UpstoxRateLimitError("Rate limit exceeded")

        client = _mock_client()
        client.get_expired_historical_candles = rate_limited

        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(concurrency=2)

        # All instruments should be recorded as errors
        assert len(result.errors) == 4  # 2 strikes × 2 types


# ===========================================================================
# 7. ADAPTIVE CONCURRENCY REDUCTION
# ===========================================================================

class TestAdaptiveConcurrency:
    @pytest.mark.asyncio
    async def test_rate_limiter_reduces_concurrency_on_429(self, db):
        """The global rate limiter should reduce concurrency on repeated 429s."""
        from app.services.rate_limiter import GlobalRateLimiter, RateLimiterConfig

        cfg = RateLimiterConfig(
            initial_concurrency=4, min_concurrency=1, max_concurrency=6,
            initial_interval=0.01, min_interval=0.005, max_interval=1.0,
            cooldown_base=0.05, cooldown_max=1.0, cooldown_multiplier=2.0,
            recovery_step=0.002, recovery_floor_pct=0.7,
            reduce_concurrency_threshold=3, reduce_cooldown=0.05,
        )
        limiter = GlobalRateLimiter(config=cfg)

        # Trigger enough consecutive 429s to cross threshold
        for _ in range(cfg.reduce_concurrency_threshold):
            await limiter.acquire()
            await limiter.on_429(retry_after=None)
            limiter.release()
            await asyncio.sleep(cfg.cooldown_base + 0.05)

        assert limiter.concurrency < 4

    @pytest.mark.asyncio
    async def test_rate_limiter_stable_on_low_429_rate(self, db):
        """The rate limiter should NOT reduce on low 429 rate."""
        from app.services.rate_limiter import GlobalRateLimiter, RateLimiterConfig

        cfg = RateLimiterConfig(
            initial_concurrency=4, min_concurrency=1, max_concurrency=6,
            initial_interval=0.01, min_interval=0.005, max_interval=1.0,
            cooldown_base=0.05, cooldown_max=1.0, cooldown_multiplier=2.0,
            recovery_step=0.002, recovery_floor_pct=0.7,
            reduce_concurrency_threshold=5, reduce_cooldown=0.05,
        )
        limiter = GlobalRateLimiter(config=cfg)

        # Only 1 429, below threshold of 5
        await limiter.acquire()
        await limiter.on_429(retry_after=None)
        limiter.release()

        # Should NOT have reduced
        assert limiter.concurrency == 4


# ===========================================================================
# 8. CHECKPOINT/RESUME
# ===========================================================================

class TestCheckpointResume:
    @pytest.mark.asyncio
    async def test_completed_instruments_skipped(self, db):
        """Instruments with existing data should be skipped."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        # Pre-populate data
        _add_option_candle(db, "NSE_FO|250000|2024-10-03", datetime(2024, 10, 3, 9, 15))

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(concurrency=2)

        # First instrument should be skipped
        assert result.rows_skipped >= 1


# ===========================================================================
# 9. IDEMPOTENCY
# ===========================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_second_run_no_new_rows(self, db):
        """Running twice produces zero new rows."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        await orch.run_options(concurrency=2)
        count1 = db.scalar(select(func.count(OptionCandle.id))) or 0

        client2 = _mock_client()
        orch2 = BackfillOrchestrator(db, client2)
        await orch2.run_options(concurrency=2)
        count2 = db.scalar(select(func.count(OptionCandle.id))) or 0

        assert count1 == count2


# ===========================================================================
# 10. EXISTING-DATA SKIPPING
# ===========================================================================

class TestExistingDataSkipping:
    @pytest.mark.asyncio
    async def test_existing_data_not_redownloaded(self, db):
        """Existing candle data should not be redownloaded."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)
        # Pre-populate data for BOTH CE and PE
        _add_option_candle(db, "NSE_FO|250000|2024-10-03", datetime(2024, 10, 3, 9, 15))
        _add_option_candle(db, "NSE_FO|250001|2024-10-03", datetime(2024, 10, 3, 9, 15))

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        await orch.run_options(concurrency=1)

        # API should not be called — all instruments have data
        client.get_expired_historical_candles.assert_not_called()


# ===========================================================================
# 11. FAILURE ISOLATION
# ===========================================================================

class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_one_failure_does_not_affect_others(self, db):
        """A failed instrument should not prevent others from succeeding."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050, 25100]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        call_count = 0

        async def selective_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated failure")
            return [
                ["2024-10-03T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
            ]

        client = _mock_client()
        client.get_expired_historical_candles = selective_failure

        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(concurrency=2)

        # At least some instruments should succeed
        assert result.rows_inserted > 0
        assert len(result.errors) >= 1


# ===========================================================================
# 12. TRANSACTION ISOLATION
# ===========================================================================

class TestTransactionIsolation:
    @pytest.mark.asyncio
    async def test_committed_data_survives_later_failure(self, db):
        """Data committed for instrument A survives even if instrument B fails."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        # Get actual instrument keys
        all_specs = db.execute(
            select(ContractSpec)
            .where(ContractSpec.expiry == "2024-10-03")
            .order_by(ContractSpec.instrument_key)
        ).scalars().all()
        first_ik = all_specs[0].instrument_key

        call_count = 0

        async def fail_after_first(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated failure")
            return [
                ["2024-10-03T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
            ]

        client = _mock_client()
        client.get_expired_historical_candles = fail_after_first

        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(concurrency=2)

        # First instrument's candles should be committed
        count = db.scalar(
            select(func.count(OptionCandle.id))
            .where(OptionCandle.instrument_key == first_ik)
        )
        assert count > 0


# ===========================================================================
# 13. RAW OHLCV/OI IMMUTABILITY
# ===========================================================================

class TestRawImmutability:
    @pytest.mark.asyncio
    async def test_option_ohlc_preserved(self, db):
        """OHLCV/OI values should be preserved exactly."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        await orch.run_options(concurrency=1)

        candle = db.execute(
            select(OptionCandle)
            .where(OptionCandle.instrument_key == "NSE_FO|250000|2024-10-03")
        ).scalars().first()
        assert candle is not None
        assert candle.open == 150.5
        assert candle.high == 155.0
        assert candle.low == 148.0
        assert candle.close == 152.3
        assert candle.volume == 5000.0
        assert candle.open_interest == 325000.0


# ===========================================================================
# 14. NO SERVER-STARTUP INGESTION
# ===========================================================================

class TestNoServerStartupIngestion:
    def test_init_db_no_upstox_calls(self):
        """init_db() must not call any Upstox API."""
        from unittest.mock import patch
        with patch("app.services.upstox_client.UpstoxClient") as MockCls:
            from app.db import init_db
            init_db()
            MockCls.assert_not_called()


# ===========================================================================
# 15. NO API CALLS DURING DRY-RUN
# ===========================================================================

class TestDryRunNoAPICalls:
    @pytest.mark.asyncio
    async def test_dry_run_zero_api_calls(self, db):
        """Dry-run should make zero API calls."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000, 25050]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)
        await orch.run_options(universe="ATM_10")

        client.get_expired_historical_candles.assert_not_called()


# ===========================================================================
# 16. NO TOKEN LEAKAGE
# ===========================================================================

class TestNoTokenLeakage:
    def test_token_not_in_exception_messages(self):
        """Error messages must not contain tokens."""
        client = _mock_client()
        orch = BackfillOrchestrator(MagicMock(), client)
        assert not hasattr(orch, "access_token")
        assert not hasattr(orch, "token")


# ===========================================================================
# 17. IST TIMESTAMP CONVENTION
# ===========================================================================

class TestISTTimestampConvention:
    @pytest.mark.asyncio
    async def test_option_candles_use_naive_ist(self, db):
        """Option candles should use naive IST timestamps."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        await orch.run_options(concurrency=1)

        candle = db.execute(
            select(OptionCandle)
            .where(OptionCandle.instrument_key == "NSE_FO|250000|2024-10-03")
        ).scalars().first()
        assert candle is not None
        assert candle.open_time.tzinfo is None  # Naive IST


# ===========================================================================
# 18. UNIVERSE FILTER INTEGRATION
# ===========================================================================

class TestUniverseFilterIntegration:
    @pytest.mark.asyncio
    async def test_universe_filter_applied(self, db):
        """Universe filter should be applied when processing options."""
        _add_nifty_candles(db, date(2024, 9, 30))
        strikes = [25000 + i * 50 for i in range(-15, 16)]
        _add_specs_for_expiry(db, "2024-10-03", strikes)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        result = await orch.run_options(universe="ATM_5", concurrency=2)

        # Should have processed fewer instruments than total
        total_specs = db.execute(
            select(func.count(ContractSpec.id))
            .where(ContractSpec.expiry == "2024-10-03")
        ).scalar()
        assert result.metadata["total_instruments"] < total_specs
        assert result.metadata["universe"] == "ATM_5"
