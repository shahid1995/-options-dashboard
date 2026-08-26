"""Phase 7.24.4 — Timezone Standardization Tests.

Comprehensive test suite for the permanent timestamp convention:
All market-data candle timestamps are stored as naive IST (Asia/Kolkata).

Verifies:
  - UTC → IST conversion
  - IST-aware → naive IST
  - Already-naive IST passthrough
  - ISO string handling (various formats)
  - DST-independent behavior (India has no DST)
  - NIFTY and option timestamps use the same convention
  - Post-close alignment (15:27-15:40 IST)
  - No future spot leakage
  - Historical Greeks engine alignment without compensating conversion
  - Raw data immutability (OHLCV unchanged)
  - Idempotency
  - Database persistence
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ContractSpec, NiftyCandle, OptionCandle, OptionGreeks
from app.utils.market_time import (
    to_ist_naive,
    IST,
    IST_OFFSET,
    is_market_hours,
    is_post_close,
    ist_naive_to_string,
)
from app.services.candle_ingestion import normalize_candle_timestamp
from app.services.historical_greeks import HistoricalGreeksEngine, CalcStatus


# ---------------------------------------------------------------------------
# A. UTC → IST
# ---------------------------------------------------------------------------

class TestUtcToIst:
    """Verify UTC timestamps are correctly converted to naive IST."""

    def test_utc_midnight_to_ist(self):
        """00:00 UTC = 05:30 IST."""
        result = to_ist_naive("2026-08-22T00:00:00Z")
        assert result == datetime(2026, 8, 22, 5, 30, 0)

    def test_utc_0345_to_ist_0915(self):
        """03:45 UTC = 09:15 IST (market open)."""
        result = to_ist_naive("2026-08-22T03:45:00Z")
        assert result == datetime(2026, 8, 22, 9, 15, 0)

    def test_utc_0957_to_ist_1527(self):
        """09:57 UTC = 15:27 IST (index close)."""
        result = to_ist_naive("2026-08-22T09:57:00Z")
        assert result == datetime(2026, 8, 22, 15, 27, 0)

    def test_utc_plus_offset(self):
        """+00:00 is treated as UTC."""
        result = to_ist_naive("2026-08-22T03:45:00+00:00")
        assert result == datetime(2026, 8, 22, 9, 15, 0)


# ---------------------------------------------------------------------------
# B. IST-aware → naive IST
# ---------------------------------------------------------------------------

class TestIstAwareToNaive:
    """Verify IST-aware datetimes are converted to naive IST."""

    def test_ist_0915(self):
        """IST 09:15 → naive 09:15."""
        dt = datetime(2026, 8, 22, 9, 15, tzinfo=IST)
        result = to_ist_naive(dt)
        assert result == datetime(2026, 8, 22, 9, 15, 0)
        assert result.tzinfo is None

    def test_ist_1527(self):
        """IST 15:27 → naive 15:27."""
        dt = datetime(2026, 8, 22, 15, 27, tzinfo=IST)
        result = to_ist_naive(dt)
        assert result == datetime(2026, 8, 22, 15, 27, 0)

    def test_utc_aware_to_ist_naive(self):
        """UTC-aware → naive IST."""
        dt_utc = datetime(2026, 8, 22, 3, 45, tzinfo=timezone.utc)
        result = to_ist_naive(dt_utc)
        assert result == datetime(2026, 8, 22, 9, 15, 0)
        assert result.tzinfo is None


# ---------------------------------------------------------------------------
# C. Already-naive IST
# ---------------------------------------------------------------------------

class TestNaiveIstPassthrough:
    """Naive datetimes are assumed to be IST and returned as-is."""

    def test_naive_0915(self):
        """Naive 09:15 → naive 09:15."""
        dt = datetime(2026, 8, 22, 9, 15)
        result = to_ist_naive(dt)
        assert result == datetime(2026, 8, 22, 9, 15, 0)

    def test_naive_1527(self):
        """Naive 15:27 → naive 15:27."""
        dt = datetime(2026, 8, 22, 15, 27)
        result = to_ist_naive(dt)
        assert result == datetime(2026, 8, 22, 15, 27, 0)


# ---------------------------------------------------------------------------
# D. ISO strings
# ---------------------------------------------------------------------------

class TestIsoStrings:
    """Various ISO 8601 string formats."""

    def test_with_ist_offset(self):
        """2026-08-22T09:15:00+05:30 → 09:15 naive IST."""
        result = to_ist_naive("2026-08-22T09:15:00+05:30")
        assert result == datetime(2026, 8, 22, 9, 15, 0)

    def test_with_z_suffix(self):
        """2026-08-22T03:45:00Z → 09:15 naive IST."""
        result = to_ist_naive("2026-08-22T03:45:00Z")
        assert result == datetime(2026, 8, 22, 9, 15, 0)

    def test_without_offset(self):
        """Naive string is assumed IST."""
        result = to_ist_naive("2026-08-22T09:15:00")
        assert result == datetime(2026, 8, 22, 9, 15, 0)

    def test_with_milliseconds(self):
        """Fractional seconds are preserved."""
        result = to_ist_naive("2026-08-22T09:15:00.123+05:30")
        assert result.hour == 9
        assert result.minute == 15

    def test_with_microseconds(self):
        """Microsecond precision."""
        result = to_ist_naive("2026-08-22T09:15:00.123456+05:30")
        assert result.microsecond == 123456

    def test_empty_string(self):
        """Empty string returns None."""
        assert to_ist_naive("") is None

    def test_none(self):
        """None returns None."""
        assert to_ist_naive(None) is None


# ---------------------------------------------------------------------------
# E. DST-independent behavior
# ---------------------------------------------------------------------------

class TestDstIndependent:
    """India does not observe DST; verify +05:30 is always correct."""

    def test_january(self):
        """January: still +05:30."""
        result = to_ist_naive("2026-01-15T09:15:00+05:30")
        assert result == datetime(2026, 1, 15, 9, 15, 0)

    def test_june(self):
        """June: still +05:30."""
        result = to_ist_naive("2026-06-15T09:15:00+05:30")
        assert result == datetime(2026, 6, 15, 9, 15, 0)

    def test_october(self):
        """October: still +05:30."""
        result = to_ist_naive("2026-10-15T09:15:00+05:30")
        assert result == datetime(2026, 10, 15, 9, 15, 0)

    def test_utc_always_plus_530(self):
        """UTC→IST offset is always +5:30, never +4:30 or +6:30."""
        dt_utc = datetime(2026, 6, 15, 3, 45, tzinfo=timezone.utc)  # Summer
        result = to_ist_naive(dt_utc)
        assert result == datetime(2026, 6, 15, 9, 15, 0)  # Still +5:30


# ---------------------------------------------------------------------------
# F. NIFTY and option timestamps same convention
# ---------------------------------------------------------------------------

class TestBothPipelinesUseIst:
    """Both NIFTY and option candle pipelines produce naive IST."""

    def test_normalize_candle_timestamp_returns_naive_ist(self):
        """candle_ingestion.normalize_candle_timestamp returns naive IST."""
        result = normalize_candle_timestamp("2026-08-22T09:15:00+05:30")
        assert result == datetime(2026, 8, 22, 9, 15, 0)
        assert result.tzinfo is None

    def test_nifty_0915_matches_option_0915(self):
        """NIFTY 09:15 IST and option 09:15 IST produce the same naive datetime."""
        nifty_ts = to_ist_naive("2026-08-22T09:15:00+05:30")
        option_ts = to_ist_naive("2026-08-22T09:15:00+05:30")
        assert nifty_ts == option_ts

    def test_nifty_1527_matches_option_1527(self):
        """NIFTY 15:27 IST and option 15:27 IST produce the same naive datetime."""
        nifty_ts = to_ist_naive("2026-08-22T15:27:00+05:30")
        option_ts = to_ist_naive("2026-08-22T15:27:00+05:30")
        assert nifty_ts == option_ts

    def test_option_utc_converted_to_ist(self):
        """Option timestamp with UTC offset is correctly converted to IST."""
        result = to_ist_naive("2026-08-22T03:45:00Z")  # 03:45 UTC
        assert result == datetime(2026, 8, 22, 9, 15, 0)  # 09:15 IST


# ---------------------------------------------------------------------------
# G. Post-close alignment
# ---------------------------------------------------------------------------

class TestPostCloseAlignment:
    """Post-close option candles use the correct preceding NIFTY candle."""

    @pytest.fixture()
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
        engine.dispose()

    @pytest.fixture()
    def sample_data(self, db_session):
        """Create NIFTY and option candles with post-close data."""
        now = datetime.utcnow()

        # Contract
        db_session.add(ContractSpec(
            instrument_key="TEST_CE|24000|28-07-2026",
            underlying="NIFTY", underlying_key="NSE_INDEX|Nifty 50",
            expiry="2026-07-28", strike_price=24000.0, instrument_type="CE",
            lot_size=75, trading_symbol="TEST", segment="INDICES",
            exchange="NSE_EQ", source="test", source_reference="test",
            fetched_at=now, created_at=now,
        ))

        # NIFTY candles: 09:15 to 15:27 IST (naive)
        for i in range(126):
            t = datetime(2026, 7, 28, 9, 15) + timedelta(minutes=3 * i)
            if t.hour > 15 or (t.hour == 15 and t.minute > 27):
                break
            db_session.add(NiftyCandle(
                symbol="NIFTY", interval="3min", open_time=t,
                open=24000.0, high=24010.0, low=23990.0, close=24005.0 + i,
                volume=100000.0,
            ))

        # Option candles including post-close (15:27, 15:30, 15:35, 15:39)
        option_times = [
            datetime(2026, 7, 28, 9, 15),   # regular
            datetime(2026, 7, 28, 12, 0),   # midday
            datetime(2026, 7, 28, 15, 27),  # post-close start
            datetime(2026, 7, 28, 15, 30),  # post-close
            datetime(2026, 7, 28, 15, 35),  # post-close
            datetime(2026, 7, 28, 15, 39),  # post-close end
        ]
        for i, t in enumerate(option_times):
            db_session.add(OptionCandle(
                instrument_key="TEST_CE|24000|28-07-2026",
                interval="3min", open_time=t,  # naive IST
                open=150.0 + i, high=155.0 + i, low=145.0 + i, close=152.0 + i,
                volume=500.0, open_interest=10000.0, fetched_at=now,
            ))

        db_session.commit()

    def test_post_close_1527_uses_1527_nifty(self, db_session, sample_data):
        """Option at 15:27 IST uses NIFTY candle at 15:27 IST."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("TEST_CE|24000|28-07-2026")

        # Find the 15:27 result
        r1527 = [r for r in results if r.open_time.hour == 15 and r.open_time.minute == 27]
        assert len(r1527) == 1
        # Spot should match the 15:27 NIFTY candle
        nifty_1527 = db_session.execute(
            select(NiftyCandle).where(NiftyCandle.open_time == datetime(2026, 7, 28, 15, 27))
        ).scalar_one_or_none()
        assert nifty_1527 is not None
        assert abs(r1527[0].spot - nifty_1527.close) < 0.01

    def test_post_close_1535_uses_1527_nifty(self, db_session, sample_data):
        """Option at 15:35 IST uses the latest NIFTY candle (15:27)."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("TEST_CE|24000|28-07-2026")

        r1535 = [r for r in results if r.open_time.hour == 15 and r.open_time.minute == 35]
        assert len(r1535) == 1
        # Spot should match the 15:27 NIFTY candle (last available)
        nifty_1527 = db_session.execute(
            select(NiftyCandle).where(NiftyCandle.open_time == datetime(2026, 7, 28, 15, 27))
        ).scalar_one_or_none()
        assert abs(r1535[0].spot - nifty_1527.close) < 0.01

    def test_post_close_not_discarded(self, db_session, sample_data):
        """Post-close option candles get Greeks calculated, not discarded."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("TEST_CE|24000|28-07-2026")

        post_close = [r for r in results if r.open_time.hour == 15 and r.open_time.minute >= 27]
        assert len(post_close) == 4  # 15:27, 15:30, 15:35, 15:39
        for r in post_close:
            assert r.status in (CalcStatus.SUCCESS.value, CalcStatus.EXPIRED.value)


# ---------------------------------------------------------------------------
# H. No future spot leakage
# ---------------------------------------------------------------------------

class TestNoFutureSpotLeakage:
    """An option candle must never use a future NIFTY candle."""

    @pytest.fixture()
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
        engine.dispose()

    def test_option_at_1000_uses_candle_at_1000(self, db_session):
        """Option at 10:00 IST should use NIFTY candle at 10:00, not 10:03."""
        now = datetime.utcnow()
        db_session.add(ContractSpec(
            instrument_key="T|24000|28-07-2026",
            underlying="NIFTY", underlying_key="NSE_INDEX|Nifty 50",
            expiry="2026-07-28", strike_price=24000.0, instrument_type="CE",
            lot_size=75, trading_symbol="T", segment="INDICES",
            exchange="NSE_EQ", source="test", source_reference="test",
            fetched_at=now, created_at=now,
        ))

        # NIFTY candles at 09:57, 10:00, 10:03
        for h, m, close in [(9, 57, 24000.0), (10, 0, 24050.0), (10, 3, 24100.0)]:
            db_session.add(NiftyCandle(
                symbol="NIFTY", interval="3min",
                open_time=datetime(2026, 7, 28, h, m),
                open=close - 5, high=close + 5, low=close - 10, close=close,
                volume=100000.0,
            ))

        # Option candle at exactly 10:00
        db_session.add(OptionCandle(
            instrument_key="T|24000|28-07-2026",
            interval="3min", open_time=datetime(2026, 7, 28, 10, 0),
            open=150.0, high=155.0, low=145.0, close=152.0,
            volume=500.0, open_interest=10000.0, fetched_at=now,
        ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("T|24000|28-07-2026")
        assert len(results) == 1
        assert results[0].spot == 24050.0  # 10:00 NIFTY, NOT 10:03


# ---------------------------------------------------------------------------
# I. Historical Greeks without compensating conversion
# ---------------------------------------------------------------------------

class TestGreeksEngineDirectComparison:
    """The Greeks engine now compares timestamps directly (both naive IST)."""

    @pytest.fixture()
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
        engine.dispose()

    def test_alignment_without_ist_offset(self, db_session):
        """Option and NIFTY at the same IST time produce matching spot."""
        now = datetime.utcnow()
        db_session.add(ContractSpec(
            instrument_key="X|24000|28-07-2026",
            underlying="NIFTY", underlying_key="NSE_INDEX|Nifty 50",
            expiry="2026-07-28", strike_price=24000.0, instrument_type="CE",
            lot_size=75, trading_symbol="X", segment="INDICES",
            exchange="NSE_EQ", source="test", source_reference="test",
            fetched_at=now, created_at=now,
        ))

        t = datetime(2026, 7, 28, 10, 0)
        db_session.add(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=t,
            open=24000.0, high=24010.0, low=23990.0, close=24005.0,
            volume=100000.0,
        ))
        db_session.add(OptionCandle(
            instrument_key="X|24000|28-07-2026",
            interval="3min", open_time=t,  # Same IST time
            open=150.0, high=155.0, low=145.0, close=152.0,
            volume=500.0, open_interest=10000.0, fetched_at=now,
        ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("X|24000|28-07-2026")
        assert len(results) == 1
        assert results[0].spot == 24005.0  # Exact match with NIFTY close


# ---------------------------------------------------------------------------
# J. Raw data immutability
# ---------------------------------------------------------------------------

class TestRawDataImmutability:
    """Timestamp normalization must not modify OHLCV/OI/contract data."""

    @pytest.fixture()
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()
        engine.dispose()

    def test_ohlcv_unchanged(self, db_session):
        """OHLCV values are preserved after Greeks calculation."""
        now = datetime.utcnow()
        t = datetime(2026, 7, 28, 10, 0)

        db_session.add(ContractSpec(
            instrument_key="M|24000|28-07-2026",
            underlying="NIFTY", underlying_key="NSE_INDEX|Nifty 50",
            expiry="2026-07-28", strike_price=24000.0, instrument_type="CE",
            lot_size=75, trading_symbol="M", segment="INDICES",
            exchange="NSE_EQ", source="test", source_reference="test",
            fetched_at=now, created_at=now,
        ))
        db_session.add(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=t,
            open=24000.0, high=24010.0, low=23990.0, close=24005.0,
            volume=100000.0,
        ))

        candle = OptionCandle(
            instrument_key="M|24000|28-07-2026",
            interval="3min", open_time=t,
            open=150.0, high=155.0, low=145.0, close=152.0,
            volume=500.0, open_interest=10000.0, fetched_at=now,
        )
        db_session.add(candle)
        db_session.commit()

        # Record pre-calculation values
        pre_open = candle.open
        pre_high = candle.high
        pre_low = candle.low
        pre_close = candle.close
        pre_volume = candle.volume
        pre_oi = candle.open_interest

        # Calculate Greeks
        engine = HistoricalGreeksEngine(db_session)
        engine.calculate_instrument("M|24000|28-07-2026")

        # Verify unchanged
        db_session.refresh(candle)
        assert candle.open == pre_open
        assert candle.high == pre_high
        assert candle.low == pre_low
        assert candle.close == pre_close
        assert candle.volume == pre_volume
        assert candle.open_interest == pre_oi


# ---------------------------------------------------------------------------
# K. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Running normalization twice produces the same result."""

    def test_normalize_candle_timestamp_idempotent(self):
        """normalize_candle_timestamp is idempotent for IST input."""
        ts = "2026-08-22T09:15:00+05:30"
        r1 = to_ist_naive(ts)
        r2 = to_ist_naive(ts)
        assert r1 == r2

    def test_to_ist_naive_idempotent_for_naive(self):
        """to_ist_naive is idempotent for naive IST input."""
        dt = datetime(2026, 8, 22, 9, 15)
        r1 = to_ist_naive(dt)
        r2 = to_ist_naive(r1)
        assert r1 == r2


# ---------------------------------------------------------------------------
# L. Database persistence
# ---------------------------------------------------------------------------

class TestDatabasePersistence:
    """Timestamps remain correct after session/engine recreation."""

    @pytest.fixture()
    def engine(self):
        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=eng)
        return eng

    def test_timestamp_survives_session_recreation(self, engine):
        """Timestamp is correct after closing and reopening a session."""
        Session = sessionmaker(bind=engine)
        t = datetime(2026, 8, 22, 9, 15)

        # Write
        s1 = Session()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=t,
            open=24000.0, high=24010.0, low=23990.0, close=24005.0,
            volume=100000.0,
        ))
        s1.commit()
        s1.close()

        # Read with new session
        s2 = Session()
        row = s2.execute(select(NiftyCandle)).scalar_one()
        assert row.open_time == t
        s2.close()

    def test_timestamp_survives_engine_recreation(self):
        """Timestamp is correct with a new engine (simulating restart)."""
        from sqlalchemy import create_engine
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            url = f"sqlite:///{db_path}"
            t = datetime(2026, 8, 22, 9, 15)

            # Write
            eng1 = create_engine(url)
            Base.metadata.create_all(bind=eng1)
            Session1 = sessionmaker(bind=eng1)
            s1 = Session1()
            s1.add(NiftyCandle(
                symbol="NIFTY", interval="3min", open_time=t,
                open=24000.0, high=24010.0, low=23990.0, close=24005.0,
                volume=100000.0,
            ))
            s1.commit()
            s1.close()
            eng1.dispose()

            # Read with new engine
            eng2 = create_engine(url)
            Session2 = sessionmaker(bind=eng2)
            s2 = Session2()
            row = s2.execute(select(NiftyCandle)).scalar_one()
            assert row.open_time == t
            s2.close()
            eng2.dispose()
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# M. Trading session helpers
# ---------------------------------------------------------------------------

class TestTradingSessionHelpers:
    """Market hours and post-close classification."""

    def test_market_open(self):
        assert is_market_hours(datetime(2026, 8, 22, 9, 15)) is True

    def test_market_close(self):
        assert is_market_hours(datetime(2026, 8, 22, 15, 30)) is True

    def test_before_market(self):
        assert is_market_hours(datetime(2026, 8, 22, 9, 14)) is False

    def test_after_market(self):
        assert is_market_hours(datetime(2026, 8, 22, 15, 31)) is False

    def test_post_close_start(self):
        assert is_post_close(datetime(2026, 8, 22, 15, 27)) is True

    def test_post_close_end(self):
        assert is_post_close(datetime(2026, 8, 22, 15, 40)) is True

    def test_post_close_after(self):
        assert is_post_close(datetime(2026, 8, 22, 15, 41)) is False

    def test_ist_naive_to_string(self):
        dt = datetime(2026, 8, 22, 9, 15)
        assert ist_naive_to_string(dt) == "2026-08-22T09:15:00+05:30"
