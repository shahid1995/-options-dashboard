"""Phase 7.12 -- Synthetic tests for the proposed OptionCandle architecture.

Tests the schema design, uniqueness constraints, and backfill logic
using small synthetic datasets. No live API calls are made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy import Integer, Float, String, DateTime

from app.models import ContractSpec, NiftyCandle


# ---------------------------------------------------------------------------
# Isolated test Base — does NOT pollute production Base.metadata
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class OptionCandle(_TestBase):
    """Proposed OptionCandle model for Phase 7.12 testing."""

    __tablename__ = "option_candles_test"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(64), index=True)
    interval: Mapped[str] = mapped_column(String(8), default="3min")
    open_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    open_interest: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="UPSTOX_EXPIRED_CANDLE")
    fetched_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("instrument_key", "interval", "open_time", name="uq_option_candle_identity"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    from app.db import Base as ProdBase
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create tables from both the test Base and the production models
    # that this test needs (ContractSpec, NiftyCandle)
    _TestBase.metadata.create_all(engine)
    ProdBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        _TestBase.metadata.drop_all(engine)
        ProdBase.metadata.drop_all(engine)


# Synthetic contract specs
CONTRACT_2024_PE = {
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

CONTRACT_2025_CE = {
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


def _make_candle(instrument_key: str, ts: datetime, open_p: float = 100.0) -> dict:
    """Create a synthetic option candle dict."""
    return {
        "instrument_key": instrument_key,
        "interval": "3min",
        "open_time": ts,
        "open": open_p,
        "high": open_p + 5,
        "low": open_p - 3,
        "close": open_p + 2,
        "volume": 1500.0,
        "open_interest": 50000.0,
        "source": "UPSTOX_EXPIRED_CANDLE",
        "fetched_at": datetime.now(timezone.utc),
    }


def _insert_candle(db, candle: dict) -> None:
    """Insert a single option candle."""
    row = OptionCandle(**candle)
    db.add(row)
    db.commit()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestOptionCandleSchema:
    def test_basic_insert_and_read(self, db):
        """Verify basic insert and read-back."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        _insert_candle(db, candle)

        rows = db.execute(select(OptionCandle)).scalars().all()
        assert len(rows) == 1
        assert rows[0].instrument_key == "NSE_FO|48891|31-10-2024"
        assert rows[0].open == 100.0
        assert rows[0].volume == 1500.0
        assert rows[0].open_interest == 50000.0

    def test_unique_constraint_prevents_duplicates(self, db):
        """Same (instrument_key, interval, open_time) should be rejected."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        _insert_candle(db, candle)

        # Second insert with same identity should fail
        with pytest.raises(Exception):
            _insert_candle(db, candle)

    def test_different_instruments_cannot_conflict(self, db):
        """Different instrument_keys at the same time are separate records."""
        c1 = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45), 100.0)
        c2 = _make_candle("NSE_FO|47982|17-04-2025", datetime(2024, 10, 31, 3, 45), 200.0)
        _insert_candle(db, c1)
        _insert_candle(db, c2)

        rows = db.execute(select(OptionCandle)).scalars().all()
        assert len(rows) == 2
        assert rows[0].open == 100.0
        assert rows[1].open == 200.0

    def test_different_intervals_are_separate(self, db):
        """Different intervals at the same time are separate records."""
        c1 = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        c1["interval"] = "3min"
        c2 = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        c2["interval"] = "5min"
        _insert_candle(db, c1)
        _insert_candle(db, c2)

        rows = db.execute(select(OptionCandle)).scalars().all()
        assert len(rows) == 2

    def test_different_timestamps_are_separate(self, db):
        """Different timestamps are separate records."""
        t1 = datetime(2024, 10, 31, 3, 45)
        t2 = datetime(2024, 10, 31, 3, 48)
        c1 = _make_candle("NSE_FO|48891|31-10-2024", t1)
        c2 = _make_candle("NSE_FO|48891|31-10-2024", t2)
        _insert_candle(db, c1)
        _insert_candle(db, c2)

        rows = db.execute(select(OptionCandle)).scalars().all()
        assert len(rows) == 2

    def test_oi_preserved_exactly(self, db):
        """Open interest is stored exactly as provided."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        candle["open_interest"] = 325300.0
        _insert_candle(db, candle)

        row = db.execute(select(OptionCandle)).scalar_one()
        assert row.open_interest == 325300.0

    def test_volume_preserved_exactly(self, db):
        """Volume is stored exactly as provided."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        candle["volume"] = 2075.0
        _insert_candle(db, candle)

        row = db.execute(select(OptionCandle)).scalar_one()
        assert row.volume == 2075.0


# ---------------------------------------------------------------------------
# Lot-size coexistence tests
# ---------------------------------------------------------------------------

class TestLotSizeCoexistence:
    def test_different_lot_sizes_coexist(self, db):
        """Contracts with different lot sizes can coexist."""
        # Insert contract specs with different lot sizes
        from app.services.contract_metadata import upsert_contract_spec, SOURCE_UPSTOX_EXPIRED

        r1 = upsert_contract_spec(db, CONTRACT_2024_PE, source=SOURCE_UPSTOX_EXPIRED)
        r2 = upsert_contract_spec(db, CONTRACT_2025_CE, source=SOURCE_UPSTOX_EXPIRED)

        assert r1.action == "inserted"
        assert r2.action == "inserted"

        # Verify different lot sizes
        spec1 = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|48891|31-10-2024")
        ).scalar_one()
        spec2 = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|47982|17-04-2025")
        ).scalar_one()

        assert spec1.lot_size == 25
        assert spec2.lot_size == 75
        assert spec1.lot_size != spec2.lot_size

    def test_candles_link_to_correct_lot_size(self, db):
        """Option candles for different contracts link to correct lot sizes."""
        from app.services.contract_metadata import upsert_contract_spec, SOURCE_UPSTOX_EXPIRED

        upsert_contract_spec(db, CONTRACT_2024_PE, source=SOURCE_UPSTOX_EXPIRED)
        upsert_contract_spec(db, CONTRACT_2025_CE, source=SOURCE_UPSTOX_EXPIRED)

        # Insert candles for both
        c1 = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45), 100.0)
        c2 = _make_candle("NSE_FO|47982|17-04-2025", datetime(2025, 4, 17, 3, 45), 200.0)
        _insert_candle(db, c1)
        _insert_candle(db, c2)

        # Verify linkage via instrument_key
        spec1 = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|48891|31-10-2024")
        ).scalar_one()
        spec2 = db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|47982|17-04-2025")
        ).scalar_one()

        assert spec1.lot_size == 25
        assert spec2.lot_size == 75


# ---------------------------------------------------------------------------
# Upsert simulation tests
# ---------------------------------------------------------------------------

class TestUpsertBehavior:
    def test_upsert_updates_on_conflict(self, db):
        """Simulating upsert: same key updates OHLCV values."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45), 100.0)
        _insert_candle(db, candle)

        # Manually update (simulating upsert behavior)
        row = db.execute(select(OptionCandle)).scalar_one()
        row.open = 110.0
        row.close = 112.0
        db.commit()

        updated = db.execute(select(OptionCandle)).scalar_one()
        assert updated.open == 110.0
        assert updated.close == 112.0

        # Verify no duplicate
        count = db.scalar(select(func.count(OptionCandle.id)))
        assert count == 1

    def test_no_duplicate_across_expiry_boundary(self, db):
        """Contracts from different expiries don't conflict even at same time."""
        c1 = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 9, 15))
        c2 = _make_candle("NSE_FO|47983|17-04-2025", datetime(2024, 10, 31, 9, 15))
        _insert_candle(db, c1)
        _insert_candle(db, c2)

        count = db.scalar(select(func.count(OptionCandle.id)))
        assert count == 2


# ---------------------------------------------------------------------------
# Query pattern tests
# ---------------------------------------------------------------------------

class TestQueryPatterns:
    def test_query_by_instrument_key(self, db):
        """Most common query: get all candles for one instrument."""
        for i in range(5):
            ts = datetime(2024, 10, 31, 3, 45) + timedelta(minutes=i * 3)
            _insert_candle(db, _make_candle("NSE_FO|48891|31-10-2024", ts, 100.0 + i))

        rows = db.execute(
            select(OptionCandle)
            .where(OptionCandle.instrument_key == "NSE_FO|48891|31-10-2024")
            .order_by(OptionCandle.open_time.asc())
        ).scalars().all()

        assert len(rows) == 5
        assert rows[0].open == 100.0
        assert rows[4].open == 104.0

    def test_query_by_instrument_and_time_range(self, db):
        """Query candles for one instrument in a time range."""
        for i in range(10):
            ts = datetime(2024, 10, 31, 3, 0) + timedelta(minutes=i * 3)
            _insert_candle(db, _make_candle("NSE_FO|48891|31-10-2024", ts, 100.0 + i))

        start = datetime(2024, 10, 31, 3, 9)
        end = datetime(2024, 10, 31, 3, 21)
        rows = db.execute(
            select(OptionCandle)
            .where(OptionCandle.instrument_key == "NSE_FO|48891|31-10-2024")
            .where(OptionCandle.open_time >= start)
            .where(OptionCandle.open_time <= end)
        ).scalars().all()

        assert len(rows) == 5  # 3:09, 3:12, 3:15, 3:18, 3:21

    def test_query_all_instruments_at_timestamp(self, db):
        """Query all instruments at one timestamp (option chain reconstruction)."""
        ts = datetime(2024, 10, 31, 9, 15)
        for strike in [22000, 22250, 22500]:
            for opt_type in ["CE", "PE"]:
                ik = f"NSE_FO|TEST|{strike}|{opt_type}"
                _insert_candle(db, _make_candle(ik, ts, float(strike)))

        rows = db.execute(
            select(OptionCandle).where(OptionCandle.open_time == ts)
        ).scalars().all()

        assert len(rows) == 6  # 3 strikes × 2 types

    def test_count_distinct_instruments(self, db):
        """Count distinct instruments with candle data."""
        ts = datetime(2024, 10, 31, 9, 15)
        for i, ik in enumerate(["A", "B", "C", "A", "B"]):
            t = ts + timedelta(minutes=i * 3)
            _insert_candle(db, _make_candle(ik, t))

        count = db.scalar(
            select(func.count(func.distinct(OptionCandle.instrument_key)))
        )
        assert count == 3


# ---------------------------------------------------------------------------
# Backfill checkpoint tests
# ---------------------------------------------------------------------------

class TestBackfillCheckpoint:
    def test_checkpoint_identifies_completed_contracts(self, db):
        """Checkpoint logic: which contracts have candle data."""
        # Insert candles for 2 of 3 contracts
        _insert_candle(db, _make_candle("CONTRACT_A", datetime(2024, 10, 31, 9, 15)))
        _insert_candle(db, _make_candle("CONTRACT_B", datetime(2024, 10, 31, 9, 15)))

        # All known contracts
        all_contracts = ["CONTRACT_A", "CONTRACT_B", "CONTRACT_C"]

        # Completed contracts (have candle data)
        completed = db.execute(
            select(OptionCandle.instrument_key).distinct()
        ).scalars().all()

        remaining = [c for c in all_contracts if c not in completed]
        assert remaining == ["CONTRACT_C"]

    def test_resume_skips_already_fetched(self, db):
        """Resume logic: skip contracts that already have data."""
        # Pre-populate with some data
        for i in range(3):
            _insert_candle(db, _make_candle(
                f"CONTRACT_{i}", datetime(2024, 10, 31, 9, 15)
            ))

        # Check which need fetching
        completed = set(db.execute(
            select(OptionCandle.instrument_key).distinct()
        ).scalars().all())

        all_contracts = [f"CONTRACT_{i}" for i in range(5)]
        to_fetch = [c for c in all_contracts if c not in completed]

        assert to_fetch == ["CONTRACT_3", "CONTRACT_4"]


# ---------------------------------------------------------------------------
# Validation simulation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_candle_accepted(self, db):
        """A candle passing all validation rules is persisted."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        _insert_candle(db, candle)

        count = db.scalar(select(func.count(OptionCandle.id)))
        assert count == 1

    def test_zero_volume_is_valid(self, db):
        """Zero volume is a soft warning, not a rejection."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        candle["volume"] = 0.0
        _insert_candle(db, candle)

        row = db.execute(select(OptionCandle)).scalar_one()
        assert row.volume == 0.0

    def test_zero_oi_is_valid(self, db):
        """Zero OI is a soft warning, not a rejection."""
        candle = _make_candle("NSE_FO|48891|31-10-2024", datetime(2024, 10, 31, 3, 45))
        candle["open_interest"] = 0.0
        _insert_candle(db, candle)

        row = db.execute(select(OptionCandle)).scalar_one()
        assert row.open_interest == 0.0
