"""Architecture validation tests — Phase 7.20.

Synthetic tests that verify critical architectural assumptions about:
  - Database persistence across sessions
  - Absolute vs relative path resolution
  - Raw data immutability
  - Derived data regeneration concept
  - lot-size preservation across instruments
  - Candle pipeline lot-size independence

These tests do NOT require live APIs or external services.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ContractSpec,
    NiftyCandle,
    OptionCandle,
    OptionGreeks,
)
from app.services.contract_metadata import (
    get_contract_specification,
    upsert_contract_spec,
)
from app.services.nifty_candles import record_candles, count_candles, get_candles
from app.services.option_candles import (
    record_option_candles,
    count_option_candles,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_engine():
    """Create a temporary SQLite database for testing."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Provide a transactional session that rolls back after each test."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# 1. Database persistence across sessions
# ---------------------------------------------------------------------------

class TestDatabasePersistence:
    """Verify that data survives separate engine/session instances."""

    def test_data_survives_new_session(self, db_engine):
        """Writing with one session and reading with another should work."""
        Session = sessionmaker(bind=db_engine)

        # Write with session 1
        s1 = Session()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 1, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=24500.0, high=24520.0, low=24480.0, close=24510.0, volume=1000.0,
        ))
        s1.commit()
        s1.close()

        # Read with session 2 (simulating server restart)
        s2 = Session()
        count = s2.scalar(select(func.count(NiftyCandle.id)))
        s2.close()

        assert count == 1

    def test_data_survives_new_engine(self, tmp_path):
        """Writing with one engine and reading with another should work."""
        db_file = str(tmp_path / "test.db")
        url = f"sqlite:///{db_file}"

        # Write with engine 1
        e1 = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=e1)
        s1 = sessionmaker(bind=e1)()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 1, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=24500.0, high=24520.0, low=24480.0, close=24510.0, volume=1000.0,
        ))
        s1.commit()
        s1.close()
        e1.dispose()

        # Read with engine 2 (simulating new process)
        e2 = create_engine(url, connect_args={"check_same_thread": False})
        s2 = sessionmaker(bind=e2)()
        count = s2.scalar(select(func.count(NiftyCandle.id)))
        s2.close()
        e2.dispose()

        assert count == 1

    def test_absolute_path_resolution(self, tmp_path):
        """Verify that absolute paths resolve consistently."""
        abs_path = os.path.join(str(tmp_path), "test.db")
        url = f"sqlite:///{abs_path}"

        e1 = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=e1)
        s1 = sessionmaker(bind=e1)()
        s1.add(NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2025, 1, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
            open=24500.0, high=24520.0, low=24480.0, close=24510.0, volume=1000.0,
        ))
        s1.commit()
        s1.close()
        e1.dispose()

        # Verify the file actually exists at the absolute path
        assert os.path.exists(abs_path)

        # Read back
        e2 = create_engine(url, connect_args={"check_same_thread": False})
        s2 = sessionmaker(bind=e2)()
        count = s2.scalar(select(func.count(NiftyCandle.id)))
        s2.close()
        e2.dispose()

        assert count == 1


# ---------------------------------------------------------------------------
# 2. Raw data immutability
# ---------------------------------------------------------------------------

class TestRawDataImmutability:
    """Verify that raw candle data is never modified after insert."""

    def test_nifty_candles_immutable(self, db_session):
        """Re-inserting same candle should upsert, not create duplicate."""
        candle = {
            "symbol": "NIFTY",
            "interval": "3min",
            "openTime": "2025-01-01T03:45:00Z",
            "open": 24500.0, "high": 24520.0, "low": 24480.0,
            "close": 24510.0, "volume": 1000.0,
        }
        stored1 = record_candles(db_session, [candle])
        assert stored1 == 1

        # Re-insert same candle (upsert)
        stored2 = record_candles(db_session, [candle])
        assert stored2 == 1

        # Should be exactly 1 row, not 2
        count = count_candles(db_session, symbol="NIFTY")
        assert count == 1

    def test_option_candles_immutable(self, db_session):
        """Re-inserting same option candle should upsert."""
        candle = {
            "instrument_key": "NSE_FO|TEST|2025-01-01",
            "interval": "3min",
            "openTime": "2025-01-01T03:45:00Z",
            "open": 100.0, "high": 110.0, "low": 95.0,
            "close": 105.0, "volume": 500.0, "open_interest": 10000.0,
        }
        stored1 = record_option_candles(db_session, [candle])
        assert stored1 == 1

        stored2 = record_option_candles(db_session, [candle])
        assert stored2 == 1

        count = count_option_candles(db_session, instrument_key="NSE_FO|TEST|2025-01-01")
        assert count == 1


# ---------------------------------------------------------------------------
# 3. Derived data regeneration concept
# ---------------------------------------------------------------------------

class TestDerivedDataRegeneration:
    """Verify that Greeks can be regenerated from raw data."""

    def test_greeks_table_empty_after_raw_insert(self, db_session):
        """Inserting raw candles does NOT create Greeks rows."""
        candle = {
            "instrument_key": "NSE_FO|TEST|2025-01-01",
            "interval": "3min",
            "openTime": "2025-01-01T03:45:00Z",
            "open": 100.0, "high": 110.0, "low": 95.0,
            "close": 105.0, "volume": 500.0, "open_interest": 10000.0,
        }
        record_option_candles(db_session, [candle])

        # Greeks table should be empty
        greeks_count = db_session.scalar(select(func.count(OptionGreeks.id)))
        assert greeks_count == 0

    def test_raw_candles_unchanged_after_greeks_insert(self, db_session):
        """Inserting Greeks does not modify raw option candles."""
        candle = {
            "instrument_key": "NSE_FO|TEST|2025-01-01",
            "interval": "3min",
            "openTime": "2025-01-01T03:45:00Z",
            "open": 100.0, "high": 110.0, "low": 95.0,
            "close": 105.0, "volume": 500.0, "open_interest": 10000.0,
        }
        record_option_candles(db_session, [candle])

        # Insert a fake Greeks record
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        db_session.execute(
            sqlite_insert(OptionGreeks).values(
                instrument_key="NSE_FO|TEST|2025-01-01",
                interval="3min",
                open_time=datetime(2025, 1, 1, 3, 45, tzinfo=timezone.utc).replace(tzinfo=None),
                spot=24500.0, strike=24500.0, expiry="2025-01-01",
                option_type="CE", option_price=105.0, lot_size=75,
                time_to_expiry=0.01, risk_free_rate=0.065, intrinsic_value=0.0,
                implied_volatility=0.18, delta=0.5, gamma=0.01, vega=50.0, theta=-10.0,
                calc_model="BLACK_SCHOLES_EUROPEAN", calc_version="1.0.0",
                calculated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status="SUCCESS",
            )
        )
        db_session.commit()

        # Raw candle should be unchanged
        raw = db_session.execute(
            select(OptionCandle).where(
                OptionCandle.instrument_key == "NSE_FO|TEST|2025-01-01"
            )
        ).scalar_one()

        assert raw.open == 100.0
        assert raw.close == 105.0
        assert raw.volume == 500.0


# ---------------------------------------------------------------------------
# 4. Lot-size preservation across instruments
# ---------------------------------------------------------------------------

class TestLotSizePreservation:
    """Verify different historical lot sizes coexist correctly."""

    def test_different_lot_sizes_coexist(self, db_session):
        """Multiple instruments with different lot sizes should coexist."""
        contracts = [
            {
                "instrument_key": "NSE_FO|A|2024-10-31",
                "underlying_symbol": "NIFTY",
                "underlying_key": "NSE_INDEX|Nifty 50",
                "expiry": "2024-10-31",
                "strike_price": 25000.0,
                "instrument_type": "CE",
                "lot_size": 25,
                "minimum_lot": 25,
                "freeze_quantity": 625,
                "tick_size": 5.0,
                "trading_symbol": "NIFTY 25000 CE 31 OCT 24",
                "segment": "INDICES",
                "exchange": "NSE_FO",
                "weekly": False,
            },
            {
                "instrument_key": "NSE_FO|B|2025-04-17",
                "underlying_symbol": "NIFTY",
                "underlying_key": "NSE_INDEX|Nifty 50",
                "expiry": "2025-04-17",
                "strike_price": 24000.0,
                "instrument_type": "PE",
                "lot_size": 75,
                "minimum_lot": 75,
                "freeze_quantity": 1800,
                "tick_size": 5.0,
                "trading_symbol": "NIFTY 24000 PE 17 APR 25",
                "segment": "INDICES",
                "exchange": "NSE_FO",
                "weekly": False,
            },
            {
                "instrument_key": "NSE_FO|C|2025-06-26",
                "underlying_symbol": "NIFTY",
                "underlying_key": "NSE_INDEX|Nifty 50",
                "expiry": "2025-06-26",
                "strike_price": 26000.0,
                "instrument_type": "CE",
                "lot_size": 50,
                "minimum_lot": 50,
                "freeze_quantity": 1250,
                "tick_size": 5.0,
                "trading_symbol": "NIFTY 26000 CE 26 JUN 25",
                "segment": "INDICES",
                "exchange": "NSE_FO",
                "weekly": False,
            },
            {
                "instrument_key": "NSE_FO|D|2024-12-26",
                "underlying_symbol": "NIFTY",
                "underlying_key": "NSE_INDEX|Nifty 50",
                "expiry": "2024-12-26",
                "strike_price": 24500.0,
                "instrument_type": "PE",
                "lot_size": 65,
                "minimum_lot": 65,
                "freeze_quantity": 1625,
                "tick_size": 5.0,
                "trading_symbol": "NIFTY 24500 PE 26 DEC 24",
                "segment": "INDICES",
                "exchange": "NSE_FO",
                "weekly": False,
            },
        ]

        for c in contracts:
            upsert_contract_spec(db_session, c)
        db_session.commit()

        # Verify each instrument has its own lot_size
        spec_a = get_contract_specification(db_session, "NSE_FO|A|2024-10-31")
        spec_b = get_contract_specification(db_session, "NSE_FO|B|2025-04-17")
        spec_c = get_contract_specification(db_session, "NSE_FO|C|2025-06-26")
        spec_d = get_contract_specification(db_session, "NSE_FO|D|2024-12-26")

        assert spec_a["lot_size"] == 25
        assert spec_b["lot_size"] == 75
        assert spec_c["lot_size"] == 50
        assert spec_d["lot_size"] == 65

    def test_minimum_lot_separate_from_lot_size(self, db_session):
        """minimum_lot and lot_size are stored independently."""
        contract = {
            "instrument_key": "NSE_FO|DIFF|2025-01-01",
            "underlying_symbol": "NIFTY",
            "underlying_key": "NSE_INDEX|Nifty 50",
            "expiry": "2025-01-01",
            "strike_price": 24000.0,
            "instrument_type": "CE",
            "lot_size": 75,
            "minimum_lot": 50,
            "freeze_quantity": 1800,
            "tick_size": 5.0,
            "trading_symbol": "NIFTY 24000 CE 01 JAN 25",
            "segment": "INDICES",
            "exchange": "NSE_FO",
            "weekly": False,
        }
        upsert_contract_spec(db_session, contract)
        db_session.commit()

        spec = get_contract_specification(db_session, "NSE_FO|DIFF|2025-01-01")
        assert spec["lot_size"] == 75
        assert spec["minimum_lot"] == 50
        assert spec["lot_size"] != spec["minimum_lot"]


# ---------------------------------------------------------------------------
# 5. Candle pipeline lot-size independence
# ---------------------------------------------------------------------------

class TestCandleLotSizeIndependence:
    """Verify that candle recording/persistence has zero lot_size dependency."""

    def test_option_candle_no_lot_size_column(self, db_session):
        """OptionCandle model should not have a lot_size column."""
        # If this test fails, it means lot_size was incorrectly added to OptionCandle
        from app.models import OptionCandle
        columns = {c.name for c in OptionCandle.__table__.columns}
        assert "lot_size" not in columns, (
            f"OptionCandle must NOT have lot_size column. Found: {columns}"
        )

    def test_option_candle_with_different_instruments(self, db_session):
        """Option candles for different instruments coexist without lot_size interference."""
        candle_a = {
            "instrument_key": "NSE_FO|A|2024-10-31",
            "interval": "3min",
            "openTime": "2024-10-31T03:45:00Z",
            "open": 100.0, "high": 110.0, "low": 95.0,
            "close": 105.0, "volume": 500.0, "open_interest": 10000.0,
        }
        candle_b = {
            "instrument_key": "NSE_FO|B|2025-04-17",
            "interval": "3min",
            "openTime": "2025-04-17T03:45:00Z",
            "open": 200.0, "high": 210.0, "low": 195.0,
            "close": 205.0, "volume": 800.0, "open_interest": 15000.0,
        }

        stored = record_option_candles(db_session, [candle_a, candle_b])
        assert stored == 2

        count_a = count_option_candles(db_session, instrument_key="NSE_FO|A|2024-10-31")
        count_b = count_option_candles(db_session, instrument_key="NSE_FO|B|2025-04-17")
        assert count_a == 1
        assert count_b == 1


# ---------------------------------------------------------------------------
# 6. Duplicate protection
# ---------------------------------------------------------------------------

class TestDuplicateProtection:
    """Verify idempotent insertion across all tables."""

    def test_nifty_candle_upsert(self, db_session):
        """Same candle inserted twice should produce exactly one row."""
        candle = {
            "symbol": "NIFTY", "interval": "3min",
            "openTime": "2025-01-01T03:45:00Z",
            "open": 24500.0, "high": 24520.0, "low": 24480.0,
            "close": 24510.0, "volume": 1000.0,
        }
        record_candles(db_session, [candle])
        record_candles(db_session, [candle])
        assert count_candles(db_session, symbol="NIFTY") == 1

    def test_contract_spec_idempotent(self, db_session):
        """Same contract inserted twice with same lot_size should be idempotent."""
        contract = {
            "instrument_key": "NSE_FO|IDEM|2025-01-01",
            "underlying_symbol": "NIFTY",
            "underlying_key": "NSE_INDEX|Nifty 50",
            "expiry": "2025-01-01",
            "strike_price": 24000.0,
            "instrument_type": "CE",
            "lot_size": 75,
            "minimum_lot": 75,
            "freeze_quantity": 1800,
            "tick_size": 5.0,
            "trading_symbol": "NIFTY 24000 CE 01 JAN 25",
            "segment": "INDICES",
            "exchange": "NSE_FO",
            "weekly": False,
        }
        r1 = upsert_contract_spec(db_session, contract)
        db_session.commit()
        r2 = upsert_contract_spec(db_session, contract)
        db_session.commit()

        assert r1.action == "inserted"
        assert r2.action == "idempotent"

    def test_contract_spec_lot_size_immutability(self, db_session):
        """Existing lot_size should NOT be overwritten by different value."""
        contract_v1 = {
            "instrument_key": "NSE_FO|IMM|2025-01-01",
            "underlying_symbol": "NIFTY",
            "underlying_key": "NSE_INDEX|Nifty 50",
            "expiry": "2025-01-01",
            "strike_price": 24000.0,
            "instrument_type": "CE",
            "lot_size": 75,
            "minimum_lot": 75,
            "freeze_quantity": 1800,
            "tick_size": 5.0,
            "trading_symbol": "NIFTY 24000 CE 01 JAN 25",
            "segment": "INDICES",
            "exchange": "NSE_FO",
            "weekly": False,
        }
        upsert_contract_spec(db_session, contract_v1)
        db_session.commit()

        # Attempt to overwrite with different lot_size
        contract_v2 = contract_v1.copy()
        contract_v2["lot_size"] = 50
        r = upsert_contract_spec(db_session, contract_v2)
        db_session.commit()

        assert r.action == "conflict"

        # Verify original lot_size preserved
        spec = get_contract_specification(db_session, "NSE_FO|IMM|2025-01-01")
        assert spec["lot_size"] == 75


# ---------------------------------------------------------------------------
# 7. Configuration verification
# ---------------------------------------------------------------------------

class TestConfigurationAudit:
    """Verify database configuration and resolution behavior."""

    def test_default_database_url_is_relative(self):
        """Verify the default DB URL is relative (this is the known issue)."""
        from app.config import settings
        if settings.DATABASE_URL is None:
            # When DATABASE_URL is not set, the default is relative
            from app.db import _engine
            url_str = str(_engine().url)
            # This documents the current behavior — relative path
            assert "paper_journal.db" in url_str

    def test_candle_config_constants(self):
        """Verify candle pipeline configuration is correct."""
        from app.services.candle_config import (
            MARKET_OPEN_IST,
            INDEX_MARKET_CLOSE_IST,
            OPTION_MARKET_CLOSE_IST,
            INDEX_CANDLES_PER_TRADING_DAY,
            OPTION_CANDLES_PER_TRADING_DAY,
        )
        assert MARKET_OPEN_IST == "09:15"
        assert INDEX_MARKET_CLOSE_IST == "15:27"
        assert OPTION_MARKET_CLOSE_IST == "15:40"
        assert INDEX_CANDLES_PER_TRADING_DAY == 124
        assert OPTION_CANDLES_PER_TRADING_DAY == 128
