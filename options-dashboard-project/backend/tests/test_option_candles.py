"""Phase 7.13 -- Comprehensive tests for OptionCandle persistence layer.

Tests the OptionCandle model, normalization, persistence, idempotency,
and query helpers using synthetic/fixture data only.  No live API calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import OptionCandle, ContractSpec
from app.services.option_candles import (
    normalize_option_candle,
    normalize_option_candles,
    record_option_candles,
    count_option_candles,
    get_option_candles,
    get_distinct_instruments,
)
from app.services.contract_metadata import upsert_contract_spec, SOURCE_UPSTOX_EXPIRED


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
CONTRACT_PE_2024 = {
    "instrument_key": "NSE_FO|48891|31-10-2024",
    "underlying": "NIFTY",
    "underlying_key": "NSE_INDEX|Nifty 50",
    "expiry": "2024-10-31",
    "strike_price": 22250.0,
    "instrument_type": "PE",
    "lot_size": 25,
    "minimum_lot": 25,
    "freeze_quantity": 1800,
    "tick_size": 5.0,
    "trading_symbol": "NIFTY 22250 PE 31 OCT 24",
    "segment": "NSE_FO",
    "exchange": "NSE",
    "weekly": False,
    "source": "UPSTOX_EXPIRED",
    "source_reference": "EXPIRED_INSTRUMENTS/NIFTY/2024-10-31",
    "fetched_at": datetime.now(timezone.utc),
}

CONTRACT_CE_2025 = {
    "instrument_key": "NSE_FO|47982|17-04-2025",
    "underlying": "NIFTY",
    "underlying_key": "NSE_INDEX|Nifty 50",
    "expiry": "2025-04-17",
    "strike_price": 20400.0,
    "instrument_type": "CE",
    "lot_size": 75,
    "minimum_lot": 75,
    "freeze_quantity": 1800,
    "tick_size": 5.0,
    "trading_symbol": "NIFTY 20400 CE 17 APR 25",
    "segment": "NSE_FO",
    "exchange": "NSE",
    "weekly": False,
    "source": "UPSTOX_EXPIRED",
    "source_reference": "EXPIRED_INSTRUMENTS/NIFTY/2025-04-17",
    "fetched_at": datetime.now(timezone.utc),
}


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalizeOptionCandle:
    def test_basic_normalization(self):
        """Convert raw Upstox candle array to normalized dict."""
        raw = [
            "2024-10-31T09:15:00+05:30",
            897.05, 899.0, 894.2, 896.3,
            2075, 325300,
        ]
        result = normalize_option_candle(raw, "NSE_FO|48891|31-10-2024")

        assert result is not None
        assert result["instrument_key"] == "NSE_FO|48891|31-10-2024"
        assert result["interval"] == "3min"
        assert result["open"] == 897.05
        assert result["high"] == 899.0
        assert result["low"] == 894.2
        assert result["close"] == 896.3
        assert result["volume"] == 2075.0
        assert result["open_interest"] == 325300.0
        # Phase 7.24.4: timestamps are naive IST, no Z suffix
        assert "2024-10-31T09:15:00" == result["openTime"]

    def test_timestamp_normalized_to_utc(self):
        """IST timestamp is converted to naive IST (Phase 7.24.4)."""
        raw = ["2024-10-31T09:15:00+05:30", 100.0, 105.0, 95.0, 102.0, 1000, 50000]
        result = normalize_option_candle(raw, "TEST_KEY")

        # 09:15 IST → 09:15 naive IST (Phase 7.24.4)
        assert result["openTime"] == "2024-10-31T09:15:00"

    def test_oi_preserved(self):
        """Open interest is preserved, not discarded like in index candles."""
        raw = ["2024-10-31T09:15:00+05:30", 100.0, 105.0, 95.0, 102.0, 1000, 999999]
        result = normalize_option_candle(raw, "TEST_KEY")

        assert result["open_interest"] == 999999.0

    def test_returns_none_for_too_few_fields(self):
        """Raw candle with < 7 elements returns None."""
        raw = ["2024-10-31T09:15:00+05:30", 100.0, 105.0, 95.0, 102.0, 1000]
        result = normalize_option_candle(raw, "TEST_KEY")
        assert result is None

    def test_returns_none_for_non_numeric_price(self):
        """Raw candle with non-numeric price returns None."""
        raw = ["2024-10-31T09:15:00+05:30", "bad", 105.0, 95.0, 102.0, 1000, 50000]
        result = normalize_option_candle(raw, "TEST_KEY")
        assert result is None

    def test_returns_none_for_invalid_timestamp(self):
        """Raw candle with unparseable timestamp returns None."""
        raw = ["not-a-timestamp", 100.0, 105.0, 95.0, 102.0, 1000, 50000]
        result = normalize_option_candle(raw, "TEST_KEY")
        assert result is None

    def test_custom_interval(self):
        """Custom interval is preserved."""
        raw = ["2024-10-31T09:15:00+05:30", 100.0, 105.0, 95.0, 102.0, 1000, 50000]
        result = normalize_option_candle(raw, "TEST_KEY", interval="5min")
        assert result["interval"] == "5min"

    def test_batch_normalization(self):
        """Batch normalization processes multiple candles."""
        raw_candles = [
            ["2024-10-31T09:15:00+05:30", 100.0, 105.0, 95.0, 102.0, 1000, 50000],
            ["2024-10-31T09:18:00+05:30", 102.0, 108.0, 100.0, 106.0, 1200, 51000],
            ["2024-10-31T09:21:00+05:30", 106.0, 110.0, 104.0, 108.0, 900, 52000],
        ]
        results = normalize_option_candles(raw_candles, "TEST_KEY")

        assert len(results) == 3
        assert results[0]["open"] == 100.0
        assert results[2]["open_interest"] == 52000.0

    def test_batch_drops_invalid(self):
        """Batch normalization drops invalid candles."""
        raw_candles = [
            ["2024-10-31T09:15:00+05:30", 100.0, 105.0, 95.0, 102.0, 1000, 50000],
            ["bad-timestamp", 100.0, 105.0, 95.0, 102.0, 1000, 50000],
            ["2024-10-31T09:21:00+05:30", 106.0, 110.0, 104.0, 108.0, 900, 52000],
        ]
        results = normalize_option_candles(raw_candles, "TEST_KEY")
        assert len(results) == 2

    def test_empty_batch(self):
        """Empty batch returns empty list."""
        results = normalize_option_candles([], "TEST_KEY")
        assert results == []


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestRecordOptionCandles:
    def test_basic_insert(self, db):
        """Insert a single candle and read it back."""
        candle = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min",
            "openTime": "2024-10-31T09:15:00",
            "open": 897.05,
            "high": 899.0,
            "low": 894.2,
            "close": 896.3,
            "volume": 2075.0,
            "open_interest": 325300.0,
        }
        stored = record_option_candles(db, [candle])
        assert stored == 1

        count = count_option_candles(db)
        assert count == 1

    def test_batch_insert(self, db):
        """Insert multiple candles in one batch."""
        candles = [
            {
                "instrument_key": "NSE_FO|48891|31-10-2024",
                "interval": "3min",
                "openTime": f"2024-10-31T03:{45 + i * 3:02d}:00Z",
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 102.0 + i,
                "volume": 1000.0 + i * 100,
                "open_interest": 50000.0 + i * 1000,
            }
            for i in range(5)
        ]
        stored = record_option_candles(db, candles)
        assert stored == 5
        assert count_option_candles(db) == 5

    def test_idempotent_insert(self, db):
        """Same candle inserted twice does not create duplicate."""
        candle = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min",
            "openTime": "2024-10-31T09:15:00",
            "open": 897.05,
            "high": 899.0,
            "low": 894.2,
            "close": 896.3,
            "volume": 2075.0,
            "open_interest": 325300.0,
        }
        stored1 = record_option_candles(db, [candle])
        stored2 = record_option_candles(db, [candle])

        assert stored1 == 1
        assert stored2 == 1  # upsert counts as stored
        assert count_option_candles(db) == 1  # but no duplicate

    def test_same_batch_twice(self, db):
        """Running the same batch twice does not create duplicates."""
        candles = [
            {
                "instrument_key": "NSE_FO|48891|31-10-2024",
                "interval": "3min",
                "openTime": f"2024-10-31T03:{45 + i * 3:02d}:00Z",
                "open": 100.0 + i,
                "high": 105.0 + i,
                "low": 95.0 + i,
                "close": 102.0 + i,
                "volume": 1000.0,
                "open_interest": 50000.0,
            }
            for i in range(3)
        ]
        record_option_candles(db, candles)
        record_option_candles(db, candles)

        assert count_option_candles(db) == 3  # no duplicates

    def test_different_instruments_same_timestamp(self, db):
        """Different instrument_keys at the same time are separate records."""
        ts = "2024-10-31T09:15:00"
        c1 = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min", "openTime": ts,
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        c2 = {
            "instrument_key": "NSE_FO|47982|17-04-2025",
            "interval": "3min", "openTime": ts,
            "open": 200.0, "high": 205.0, "low": 195.0, "close": 202.0,
            "volume": 2000.0, "open_interest": 60000.0,
        }
        stored = record_option_candles(db, [c1, c2])
        assert stored == 2
        assert count_option_candles(db) == 2

    def test_different_intervals_same_instrument(self, db):
        """Different intervals at the same time are separate records."""
        ts = "2024-10-31T09:15:00"
        c1 = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min", "openTime": ts,
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        c2 = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "5min", "openTime": ts,
            "open": 100.0, "high": 106.0, "low": 94.0, "close": 103.0,
            "volume": 1500.0, "open_interest": 51000.0,
        }
        stored = record_option_candles(db, [c1, c2])
        assert stored == 2
        assert count_option_candles(db) == 2

    def test_ce_pe_coexistence(self, db):
        """CE and PE for the same strike/expiry coexist."""
        ts = "2024-10-31T09:15:00"
        ce = {
            "instrument_key": "NSE_FO|48890|31-10-2024",
            "interval": "3min", "openTime": ts,
            "open": 150.0, "high": 155.0, "low": 145.0, "close": 152.0,
            "volume": 3000.0, "open_interest": 70000.0,
        }
        pe = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min", "openTime": ts,
            "open": 897.05, "high": 899.0, "low": 894.2, "close": 896.3,
            "volume": 2075.0, "open_interest": 325300.0,
        }
        stored = record_option_candles(db, [ce, pe])
        assert stored == 2
        assert count_option_candles(db) == 2

    def test_empty_batch(self, db):
        """Empty batch returns 0."""
        stored = record_option_candles(db, [])
        assert stored == 0
        assert count_option_candles(db) == 0

    def test_malformed_record_skipped(self, db):
        """Malformed records are skipped without affecting valid ones."""
        good = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min",
            "openTime": "2024-10-31T09:15:00",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        bad = {"instrument_key": "", "interval": "3min"}  # missing everything
        bad2 = {
            "instrument_key": "X",
            "interval": "INVALID_INTERVAL",
            "openTime": "2024-10-31T09:15:00",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        stored = record_option_candles(db, [good, bad, bad2])
        assert stored == 1
        assert count_option_candles(db) == 1

    def test_z_suffix_timestamp_parsed(self, db):
        """Timestamp is correctly parsed as naive IST (Phase 7.24.4)."""
        candle = {
            "instrument_key": "TEST",
            "interval": "3min",
            "openTime": "2024-10-31T09:15:00",  # naive IST
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        record_option_candles(db, [candle])

        row = db.execute(select(OptionCandle)).scalar_one()
        # Phase 7.24.4: naive IST, not UTC
        assert row.open_time == datetime(2024, 10, 31, 9, 15)

    def test_oi_preserved_exactly(self, db):
        """Open interest is stored exactly as provided."""
        candle = {
            "instrument_key": "TEST",
            "interval": "3min",
            "openTime": "2024-10-31T09:15:00",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 2075.0, "open_interest": 325300.0,
        }
        record_option_candles(db, [candle])

        row = db.execute(select(OptionCandle)).scalar_one()
        assert row.open_interest == 325300.0
        assert row.volume == 2075.0


# ---------------------------------------------------------------------------
# Lot-size coexistence tests
# ---------------------------------------------------------------------------

class TestLotSizeCoexistence:
    def test_different_lot_sizes_through_instrument_key(self, db):
        """Different lot sizes coexist via instrument_key identity."""
        upsert_contract_spec(db, CONTRACT_PE_2024, source=SOURCE_UPSTOX_EXPIRED)
        upsert_contract_spec(db, CONTRACT_CE_2025, source=SOURCE_UPSTOX_EXPIRED)

        ts1 = "2024-10-31T09:15:00"
        ts2 = "2025-04-17T09:15:00"

        c1 = {
            "instrument_key": "NSE_FO|48891|31-10-2024",
            "interval": "3min", "openTime": ts1,
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        c2 = {
            "instrument_key": "NSE_FO|47982|17-04-2025",
            "interval": "3min", "openTime": ts2,
            "open": 200.0, "high": 205.0, "low": 195.0, "close": 202.0,
            "volume": 2000.0, "open_interest": 60000.0,
        }
        record_option_candles(db, [c1, c2])

        # Verify lot sizes are different but coexist
        spec1 = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|48891|31-10-2024")
        ).scalar_one()
        spec2 = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|47982|17-04-2025")
        ).scalar_one()

        assert spec1.lot_size == 25
        assert spec2.lot_size == 75
        assert spec1.lot_size != spec2.lot_size

        # Both have candle data
        assert count_option_candles(db, "NSE_FO|48891|31-10-2024") == 1
        assert count_option_candles(db, "NSE_FO|47982|17-04-2025") == 1

    def test_candle_identity_independent_of_lot_size(self, db):
        """Candle identity does not depend on lot_size."""
        # Two candles with same timestamp, different instruments
        c1 = {
            "instrument_key": "A",
            "interval": "3min", "openTime": "2024-10-31T09:15:00",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
            "volume": 1000.0, "open_interest": 50000.0,
        }
        c2 = {
            "instrument_key": "B",
            "interval": "3min", "openTime": "2024-10-31T09:15:00",
            "open": 200.0, "high": 205.0, "low": 195.0, "close": 202.0,
            "volume": 2000.0, "open_interest": 60000.0,
        }
        record_option_candles(db, [c1, c2])
        assert count_option_candles(db) == 2


# ---------------------------------------------------------------------------
# Query helper tests
# ---------------------------------------------------------------------------

class TestQueryHelpers:
    def test_get_option_candles(self, db):
        """Retrieve candles for one instrument ordered by time."""
        for i in range(5):
            candle = {
                "instrument_key": "TEST",
                "interval": "3min",
                "openTime": f"2024-10-31T03:{45 + i * 3:02d}:00Z",
                "open": 100.0 + i, "high": 105.0 + i,
                "low": 95.0 + i, "close": 102.0 + i,
                "volume": 1000.0, "open_interest": 50000.0,
            }
            record_option_candles(db, [candle])

        candles = get_option_candles(db, "TEST")
        assert len(candles) == 5
        assert candles[0]["open"] == 100.0
        assert candles[4]["open"] == 104.0

    def test_get_distinct_instruments(self, db):
        """Return distinct instrument_keys with candle data."""
        for ik in ["A", "B", "C", "A"]:
            candle = {
                "instrument_key": ik,
                "interval": "3min",
                "openTime": "2024-10-31T09:15:00",
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
                "volume": 1000.0, "open_interest": 50000.0,
            }
            record_option_candles(db, [candle])

        instruments = get_distinct_instruments(db)
        assert set(instruments) == {"A", "B", "C"}

    def test_count_filtered(self, db):
        """Count candles filtered by instrument_key."""
        for ik in ["A", "A", "B"]:
            candle = {
                "instrument_key": ik,
                "interval": "3min",
                "openTime": "2024-10-31T09:15:00",
                "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0,
                "volume": 1000.0, "open_interest": 50000.0,
            }
            record_option_candles(db, [candle])

        assert count_option_candles(db, "A") == 1  # deduplicated
        assert count_option_candles(db, "B") == 1
        assert count_option_candles(db) == 2


# ---------------------------------------------------------------------------
# Transaction safety tests
# ---------------------------------------------------------------------------

class TestTransactionSafety:
    def test_batch_is_atomic(self, db):
        """A batch of candles is committed atomically."""
        candles = [
            {
                "instrument_key": "TEST",
                "interval": "3min",
                "openTime": f"2024-10-31T03:{45 + i * 3:02d}:00Z",
                "open": 100.0 + i, "high": 105.0 + i,
                "low": 95.0 + i, "close": 102.0 + i,
                "volume": 1000.0, "open_interest": 50000.0,
            }
            for i in range(3)
        ]
        stored = record_option_candles(db, candles)
        assert stored == 3

        # Verify all committed
        count = count_option_candles(db)
        assert count == 3
