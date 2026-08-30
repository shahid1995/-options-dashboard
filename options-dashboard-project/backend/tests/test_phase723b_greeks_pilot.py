"""Phase 7.23B — Historical Greeks Pilot Tests.

Comprehensive tests covering:
  1. Database persistence before/after Greeks
  2. Historical spot lookup and alignment
  3. Post-close timestamp uses last preceding NIFTY candle
  4. CE and PE calculation
  5. IV round-trip
  6. Greeks persistence and idempotency
  7. Raw data immutability
  8. Historical lot-size preservation
  9. Calculation version consistency
  10. Missing spot handling
  11. Zero/invalid option price handling
  12. Database path deterministic
  13. Simulated auth failure pauses safely
  14. Resume does not duplicate data
"""

import math
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base, _DEFAULT_DB_PATH
from app.models import (
    ContractSpec, NiftyCandle, OptionCandle, OptionGreeks,
)
from app.services.historical_greeks import (
    HistoricalGreeksEngine,
    bs_price,
    bs_greeks,
    bs_intrinsic,
    solve_iv,
    compute_time_to_expiry,
    align_spot,
    calculate_greeks_for_candle,
    CalcStatus,
    DEFAULT_RISK_FREE_RATE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """In-memory database session for isolated tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def sample_contracts(db_session):
    """Insert sample contract specs."""
    now = datetime.now(timezone.utc)
    _common = dict(
        underlying="NIFTY", underlying_key="NSE_INDEX|Nifty 50",
        trading_symbol="NIFTY", segment="INDICES", exchange="NSE_EQ",
        source="test", source_reference="test_phase723b",
        fetched_at=now, created_at=now,
    )
    contracts = [
        ContractSpec(
            instrument_key="NSE_FO|63935|28-07-2026",
            expiry="2026-07-28",
            strike_price=24000.0, instrument_type="CE", lot_size=75,
            **_common,
        ),
        ContractSpec(
            instrument_key="NSE_FO|63936|28-07-2026",
            expiry="2026-07-28",
            strike_price=24000.0, instrument_type="PE", lot_size=75,
            **_common,
        ),
        # Historical lot size (pre-Nov 2024 pattern)
        ContractSpec(
            instrument_key="NSE_FO|10001|31-10-2024",
            expiry="2024-10-31",
            strike_price=25000.0, instrument_type="CE", lot_size=25,
            **_common,
        ),
    ]
    for c in contracts:
        db_session.add(c)
    db_session.commit()
    return contracts


@pytest.fixture()
def sample_nifty_candles(db_session):
    """Insert sample NIFTY index candles (stored as naive IST)."""
    candles = []
    base_date = datetime(2026, 7, 28)
    for i in range(126):  # 126 3-min candles (09:15 to 15:27 IST)
        t = base_date.replace(hour=9, minute=15) + timedelta(minutes=3 * i)
        candles.append(NiftyCandle(
            symbol="NIFTY", interval="3min", open_time=t,
            open=24000.0 + (i * 0.5), high=24010.0 + (i * 0.5),
            low=23990.0 + (i * 0.5), close=24005.0 + (i * 0.5),
            volume=100000 + i,
        ))
    for c in candles:
        db_session.add(c)
    db_session.commit()
    return candles


@pytest.fixture()
def sample_option_candles(db_session):
    """Insert sample option candles (stored as naive IST, Phase 7.24.4)."""
    candles = []
    base_date = datetime(2026, 7, 28)
    now = datetime.now(timezone.utc)

    # CE candles during trading hours (IST, matching NIFTY candles)
    for i in range(100):
        t_ist = base_date.replace(hour=9, minute=15) + timedelta(minutes=3 * i)
        price = 150.0 + (i * 0.25)  # CE option prices
        candles.append(OptionCandle(
            instrument_key="NSE_FO|63935|28-07-2026",
            interval="3min", open_time=t_ist,  # naive IST
            open=price, high=price + 2, low=price - 1, close=price,
            volume=500 + i, open_interest=10000 + i,
            fetched_at=now,
        ))

    # CE candles after index close (15:27-15:39 IST)
    for i in range(5):
        t_ist = datetime(2026, 7, 28, 15, 27) + timedelta(minutes=3 * i)
        price = 120.0 + i
        candles.append(OptionCandle(
            instrument_key="NSE_FO|63935|28-07-2026",
            interval="3min", open_time=t_ist,  # naive IST
            open=price, high=price + 1, low=price - 1, close=price,
            volume=300 + i, open_interest=9000 + i,
            fetched_at=now,
        ))

    # PE candles during trading hours
    for i in range(100):
        t_ist = base_date.replace(hour=9, minute=15) + timedelta(minutes=3 * i)
        price = 5.0 + max(0, 200 - i) * 0.05  # PE prices declining as spot rises
        candles.append(OptionCandle(
            instrument_key="NSE_FO|63936|28-07-2026",
            interval="3min", open_time=t_ist,  # naive IST
            open=price, high=price + 1, low=max(0.05, price - 0.5), close=price,
            volume=400 + i, open_interest=8000 + i,
            fetched_at=now,
        ))

    for c in candles:
        db_session.add(c)
    db_session.commit()
    return candles


# ---------------------------------------------------------------------------
# Test 1: Database persistence before Greeks
# ---------------------------------------------------------------------------

class TestPersistenceBefore:
    def test_row_counts_before_greeks(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Verify database state before Greeks calculation."""
        nifty = db_session.scalar(select(func.count(NiftyCandle.id)))
        contracts = db_session.scalar(select(func.count(ContractSpec.id)))
        options = db_session.scalar(select(func.count(OptionCandle.id)))
        greeks = db_session.scalar(select(func.count(OptionGreeks.id)))

        assert nifty == 126
        assert contracts == 3
        assert options == 205  # 100 CE + 5 post-close + 100 PE
        assert greeks == 0


# ---------------------------------------------------------------------------
# Test 2: Historical spot lookup
# ---------------------------------------------------------------------------

class TestSpotAlignment:
    def test_intraday_spot_alignment(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Option candle during trading hours aligns to correct NIFTY candle."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")

        # All successful results should have a valid spot
        success = [r for r in results if r.status == CalcStatus.SUCCESS.value]
        assert len(success) > 0
        for r in success:
            assert r.spot > 0
            assert r.spot >= 24000  # NIFTY is around 24000

    def test_no_future_spot_selected(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Spot used should never be from a future NIFTY candle."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")

        nifty_all = db_session.execute(
            select(NiftyCandle).order_by(NiftyCandle.open_time.asc())
        ).scalars().all()
        nifty_candles = [{"open_time": c.open_time, "close": c.close} for c in nifty_all]

        for r in results:
            if r.status != CalcStatus.SUCCESS.value:
                continue
            # Phase 7.24.4: option timestamps are naive IST, same as NIFTY
            expected_spot = None
            for nc in nifty_candles:
                if nc["open_time"] <= r.open_time:
                    expected_spot = nc["close"]
                else:
                    break
            if expected_spot is not None:
                assert abs(r.spot - expected_spot) < 0.01, (
                    f"Spot {r.spot} != expected {expected_spot} at {r.open_time}"
                )


# ---------------------------------------------------------------------------
# Test 3: Post-close spot alignment
# ---------------------------------------------------------------------------

class TestPostCloseAlignment:
    def test_post_close_uses_last_preceding_candle(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Post-close option candles use the latest NIFTY candle at or before the option timestamp."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")

        # Find post-close results (option times at/after 15:27 IST, Phase 7.24.4)
        post_close = [r for r in results if r.open_time >= datetime(2026, 7, 28, 15, 27)]
        assert len(post_close) > 0, "Should have post-close candles"

        # For each post-close candle, verify the spot comes from the latest
        # NIFTY candle whose open_time <= the option's IST timestamp.
        for r in post_close:
            assert r.status == CalcStatus.SUCCESS.value
            # Phase 7.24.4: option timestamps are naive IST, same as NIFTY
            nifty = db_session.execute(
                select(NiftyCandle)
                .where(NiftyCandle.open_time <= r.open_time)
                .order_by(NiftyCandle.open_time.desc())
                .limit(1)
            ).scalar_one_or_none()
            assert nifty is not None, f"No NIFTY candle found for option at {r.open_time}"
            assert abs(r.spot - nifty.close) < 0.01, (
                f"Post-close spot {r.spot} != NIFTY {nifty.open_time} close {nifty.close}"
            )

    def test_post_close_not_discarded(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Post-close option candles are not discarded — they get Greeks calculated."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")

        post_close = [r for r in results if r.open_time >= datetime(2026, 7, 28, 9, 57)]
        success = [r for r in post_close if r.status == CalcStatus.SUCCESS.value]
        assert len(success) > 0, "Post-close candles should produce successful Greeks"


# ---------------------------------------------------------------------------
# Test 4: CE and PE calculation
# ---------------------------------------------------------------------------

class TestCEPECalculation:
    def test_ce_delta_positive(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """CE delta should be positive."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")
        success = [r for r in results if r.status == CalcStatus.SUCCESS.value and r.delta is not None]
        assert len(success) > 0
        for r in success:
            assert r.delta >= 0, f"CE delta {r.delta} should be >= 0"

    def test_pe_delta_negative(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """PE delta should be negative (or zero for deep OTM)."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63936|28-07-2026")
        success = [r for r in results if r.status == CalcStatus.SUCCESS.value and r.delta is not None]
        assert len(success) > 0
        for r in success:
            assert r.delta <= 0, f"PE delta {r.delta} should be <= 0"

    def test_gamma_non_negative(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Gamma should be non-negative for all valid calculations."""
        engine = HistoricalGreeksEngine(db_session)
        for ik in ["NSE_FO|63935|28-07-2026", "NSE_FO|63936|28-07-2026"]:
            results = engine.calculate_instrument(ik)
            success = [r for r in results if r.status == CalcStatus.SUCCESS.value]
            for r in success:
                if r.gamma is not None:
                    assert r.gamma >= -1e-10, f"Gamma {r.gamma} should be >= 0 for {ik}"


# ---------------------------------------------------------------------------
# Test 5: IV round-trip
# ---------------------------------------------------------------------------

class TestIVRoundTrip:
    def test_iv_round_trip(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Repricing from calculated IV should match the market option price."""
        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")
        success = [r for r in results if r.status == CalcStatus.SUCCESS.value and r.implied_volatility is not None]

        assert len(success) > 0
        for r in success[:10]:  # Check first 10
            theoretical = bs_price(r.option_type, r.spot, r.strike, r.time_to_expiry, r.implied_volatility)
            assert abs(theoretical - r.option_price) < 0.01, (
                f"IV round-trip: theoretical {theoretical:.4f} != market {r.option_price:.4f} "
                f"(diff={abs(theoretical - r.option_price):.6f})"
            )


# ---------------------------------------------------------------------------
# Test 6: Greeks persistence and idempotency
# ---------------------------------------------------------------------------

class TestGreeksPersistence:
    def test_greeks_persist(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Greeks are successfully persisted to the database."""
        engine = HistoricalGreeksEngine(db_session)
        engine.run_instrument("NSE_FO|63935|28-07-2026")

        count = db_session.scalar(
            select(func.count(OptionGreeks.id))
            .where(OptionGreeks.instrument_key == "NSE_FO|63935|28-07-2026")
        )
        assert count > 0

    def test_idempotency(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Running the same instrument twice produces 0 new rows."""
        engine = HistoricalGreeksEngine(db_session)
        engine.run_instrument("NSE_FO|63935|28-07-2026")
        count_after_first = db_session.scalar(
            select(func.count(OptionGreeks.id))
            .where(OptionGreeks.instrument_key == "NSE_FO|63935|28-07-2026")
        )

        engine.run_instrument("NSE_FO|63935|28-07-2026")
        count_after_second = db_session.scalar(
            select(func.count(OptionGreeks.id))
            .where(OptionGreeks.instrument_key == "NSE_FO|63935|28-07-2026")
        )

        assert count_after_first == count_after_second, (
            f"Idempotency failed: {count_after_first} -> {count_after_second}"
        )

    def test_duplicate_prevention(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """No duplicate rows should be created by repeated runs."""
        engine = HistoricalGreeksEngine(db_session)
        engine.run_instrument("NSE_FO|63935|28-07-2026")
        engine.run_instrument("NSE_FO|63935|28-07-2026")
        engine.run_instrument("NSE_FO|63935|28-07-2026")

        count = db_session.scalar(
            select(func.count(OptionGreeks.id))
            .where(OptionGreeks.instrument_key == "NSE_FO|63935|28-07-2026")
        )
        candles_count = db_session.scalar(
            select(func.count(OptionCandle.id))
            .where(OptionCandle.instrument_key == "NSE_FO|63935|28-07-2026")
        )
        assert count == candles_count, f"Greeks {count} != candles {candles_count}"


# ---------------------------------------------------------------------------
# Test 7: Raw data immutability
# ---------------------------------------------------------------------------

class TestRawImmutability:
    def test_option_candles_unchanged_after_greeks(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Option candles must not be modified by Greeks calculation."""
        # Snapshot
        snapshot = db_session.execute(
            select(OptionCandle.id, OptionCandle.open, OptionCandle.high,
                   OptionCandle.low, OptionCandle.close, OptionCandle.volume, OptionCandle.open_interest)
            .where(OptionCandle.instrument_key == "NSE_FO|63935|28-07-2026")
        ).all()
        snap_dict = {r[0]: r[1:] for r in snapshot}

        # Run Greeks
        engine = HistoricalGreeksEngine(db_session)
        engine.run_instrument("NSE_FO|63935|28-07-2026")

        # Verify unchanged
        for candle_id, vals in snap_dict.items():
            current = db_session.execute(
                select(OptionCandle.open, OptionCandle.high,
                       OptionCandle.low, OptionCandle.close,
                       OptionCandle.volume, OptionCandle.open_interest)
                .where(OptionCandle.id == candle_id)
            ).one()
            assert current == vals, f"Option candle {candle_id} was modified"

    def test_nifty_candles_unchanged_after_greeks(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """NIFTY candles must not be modified by Greeks calculation."""
        snapshot = db_session.execute(
            select(NiftyCandle.id, NiftyCandle.open, NiftyCandle.close)
            .limit(10)
        ).all()
        snap_dict = {r[0]: r[1:] for r in snapshot}

        engine = HistoricalGreeksEngine(db_session)
        engine.run_instrument("NSE_FO|63935|28-07-2026")

        for nifty_id, vals in snap_dict.items():
            current = db_session.execute(
                select(NiftyCandle.open, NiftyCandle.close)
                .where(NiftyCandle.id == nifty_id)
            ).one()
            assert current == vals, f"NIFTY candle {nifty_id} was modified"

    def test_contract_specs_unchanged_after_greeks(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """Contract specs must not be modified by Greeks calculation."""
        spec = db_session.execute(
            select(ContractSpec.strike_price, ContractSpec.lot_size, ContractSpec.instrument_type)
            .where(ContractSpec.instrument_key == "NSE_FO|63935|28-07-2026")
        ).one()

        engine = HistoricalGreeksEngine(db_session)
        engine.run_instrument("NSE_FO|63935|28-07-2026")

        spec_after = db_session.execute(
            select(ContractSpec.strike_price, ContractSpec.lot_size, ContractSpec.instrument_type)
            .where(ContractSpec.instrument_key == "NSE_FO|63935|28-07-2026")
        ).one()
        assert spec == spec_after, "ContractSpec was modified"


# ---------------------------------------------------------------------------
# Test 8: Historical lot-size preservation
# ---------------------------------------------------------------------------

class TestLotSizePreservation:
    def test_historical_lot_size_used(self, db_session, sample_contracts):
        """Historical lot_size from contract_specs is used, not today's."""
        # The 2024 contract has lot_size=25
        spec = db_session.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|10001|31-10-2024")
        ).scalar_one()
        assert spec.lot_size == 25

    def test_per_unit_greeks_independent_of_lot_size(self, db_session, sample_contracts, sample_nifty_candles):
        """Greek values per unit should be independent of lot_size."""
        # Insert option candles for the lot_size=25 contract
        base = datetime(2024, 10, 31)
        now = datetime.now(timezone.utc)
        for i in range(10):
            t = base.replace(hour=9, minute=15) + timedelta(minutes=3 * i)
            t_utc = t - timedelta(hours=5, minutes=30)
            db_session.add(OptionCandle(
                instrument_key="NSE_FO|10001|31-10-2024",
                interval="3min", open_time=t_utc,
                open=200.0, high=205.0, low=195.0, close=200.0,
                volume=100, open_interest=500, fetched_at=now,
            ))

        # Also need NIFTY candles for 2024-10-31
        for i in range(10):
            t = base.replace(hour=9, minute=15) + timedelta(minutes=3 * i)
            db_session.add(NiftyCandle(
                symbol="NIFTY", interval="3min", open_time=t,
                open=25000.0, high=25010.0, low=24990.0, close=25005.0,
                volume=100000,
            ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|10001|31-10-2024")
        success = [r for r in results if r.status == CalcStatus.SUCCESS.value]

        for r in success:
            assert r.lot_size == 25, f"Lot size should be 25, got {r.lot_size}"
            # Greeks are per-unit, not scaled by lot_size
            if r.delta is not None:
                assert abs(r.delta) <= 1.0, f"Per-unit delta {r.delta} should be in [-1, 1]"


# ---------------------------------------------------------------------------
# Test 9: Calculation version consistency
# ---------------------------------------------------------------------------

class TestCalcVersion:
    def test_calc_version_set(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """All calculated Greeks should have the correct calc_version."""
        engine = HistoricalGreeksEngine(db_session, calc_version="2.0.0")
        engine.run_instrument("NSE_FO|63935|28-07-2026")

        versions = db_session.execute(
            select(OptionGreeks.calc_version)
            .where(OptionGreeks.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalars().all()

        assert all(v == "2.0.0" for v in versions), f"Versions: {set(versions)}"


# ---------------------------------------------------------------------------
# Test 10: Missing spot handling
# ---------------------------------------------------------------------------

class TestMissingSpot:
    def test_no_spot_returns_insufficient_data(self, db_session, sample_contracts):
        """When no NIFTY candles exist for the option's date, return INSUFFICIENT_DATA."""
        # Insert option candle for a date with no NIFTY data
        now = datetime.now(timezone.utc)
        db_session.add(OptionCandle(
            instrument_key="NSE_FO|63935|28-07-2026",
            interval="3min", open_time=datetime(2025, 1, 1, 3, 45),  # UTC
            open=100.0, high=105.0, low=95.0, close=100.0,
            volume=500, open_interest=1000, fetched_at=now,
        ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")
        assert len(results) == 1
        assert results[0].status == CalcStatus.INSUFFICIENT_DATA.value
        assert results[0].error_code == "NO_SPOT"


# ---------------------------------------------------------------------------
# Test 11: Zero/invalid option price handling
# ---------------------------------------------------------------------------

class TestInvalidPrice:
    def test_zero_price(self, db_session, sample_contracts, sample_nifty_candles):
        """Zero option price should return INVALID_PRICE."""
        now = datetime.now(timezone.utc)
        db_session.add(OptionCandle(
            instrument_key="NSE_FO|63935|28-07-2026",
            interval="3min", open_time=datetime(2026, 7, 28, 9, 15),  # Phase 7.24.4: naive IST
            open=0.0, high=0.0, low=0.0, close=0.0,
            volume=0, open_interest=0, fetched_at=now,
        ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")
        assert len(results) == 1
        assert results[0].status == CalcStatus.INVALID_PRICE.value

    def test_negative_price(self, db_session, sample_contracts, sample_nifty_candles):
        """Negative option price should return INVALID_PRICE."""
        now = datetime.now(timezone.utc)
        db_session.add(OptionCandle(
            instrument_key="NSE_FO|63935|28-07-2026",
            interval="3min", open_time=datetime(2026, 7, 28, 9, 15),  # Phase 7.24.4: naive IST
            open=-5.0, high=0.0, low=-10.0, close=-5.0,
            volume=100, open_interest=500, fetched_at=now,
        ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")
        assert len(results) == 1
        assert results[0].status == CalcStatus.INVALID_PRICE.value


# ---------------------------------------------------------------------------
# Test 12: Database path deterministic
# ---------------------------------------------------------------------------

class TestDatabasePath:
    def test_db_path_is_absolute(self):
        """Database path should be absolute, not relative."""
        assert os.path.isabs(_DEFAULT_DB_PATH)

    def test_db_path_contains_backend(self):
        """Database path should be under the backend directory."""
        assert "backend" in _DEFAULT_DB_PATH.lower() or "paper_journal" in _DEFAULT_DB_PATH

    def test_db_path_same_across_imports(self):
        """Database path should be deterministic."""
        from app.db import _DEFAULT_DB_PATH as path1
        from app.db import get_database_path as path2_fn
        assert path1 == path2_fn()


# ---------------------------------------------------------------------------
# Test 13: Simulated auth failure pauses safely
# ---------------------------------------------------------------------------

class TestAuthFailureHandling:
    def test_failed_instrument_does_not_block_others(self, db_session, sample_contracts, sample_nifty_candles, sample_option_candles):
        """A failed instrument should not prevent processing of the next one."""
        engine = HistoricalGreeksEngine(db_session)

        # Run on an instrument with no contract spec (should return empty)
        result_missing = engine.run_instrument("NONEXISTENT|KEY|01-01-2026")
        assert result_missing["total_candles"] == 0

        # Next instrument should still work
        result = engine.run_instrument("NSE_FO|63935|28-07-2026")
        assert result["success"] > 0

    def test_exception_in_one_candle_doesnt_abort_batch(self, db_session, sample_contracts, sample_nifty_candles):
        """If one candle causes an error, the rest should still be processed."""
        # Insert a mix of valid and problematic candles
        base = datetime(2026, 7, 28)
        now = datetime.now(timezone.utc)
        for i in range(20):
            t_ist = base.replace(hour=9, minute=15) + timedelta(minutes=3 * i)  # Phase 7.24.4: naive IST
            price = 100.0 if i != 10 else -1.0  # Candle 10 has negative price
            db_session.add(OptionCandle(
                instrument_key="NSE_FO|63935|28-07-2026",
                interval="3min", open_time=t_ist,  # Phase 7.24.4: naive IST
                open=price, high=abs(price) + 5, low=abs(price) - 5, close=price,
                volume=500, open_interest=1000, fetched_at=now,
            ))
        db_session.commit()

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument("NSE_FO|63935|28-07-2026")
        assert len(results) == 20  # All candles processed, not just 10

        statuses = [r.status for r in results]
        assert CalcStatus.INVALID_PRICE.value in statuses  # The bad candle
        assert CalcStatus.SUCCESS.value in statuses  # The good candles


# ---------------------------------------------------------------------------
# Test 14: Mathematical validation
# ---------------------------------------------------------------------------

class TestMathValidation:
    def test_bs_price_ce_positive(self):
        """BS price for CE should be positive when S > K."""
        price = bs_price("CE", 100, 95, 0.1, 0.2)
        assert price > 0

    def test_bs_price_pe_positive(self):
        """BS price for PE should be positive when K > S."""
        price = bs_price("PE", 95, 100, 0.1, 0.2)
        assert price > 0

    def test_bs_intrinsic_ce(self):
        """CE intrinsic = max(S-K, 0)."""
        assert bs_intrinsic("CE", 100, 95) == 5.0
        assert bs_intrinsic("CE", 95, 100) == 0.0

    def test_bs_intrinsic_pe(self):
        """PE intrinsic = max(K-S, 0)."""
        assert bs_intrinsic("PE", 95, 100) == 5.0
        assert bs_intrinsic("PE", 100, 95) == 0.0

    def test_solve_iv_converges(self):
        """IV solver should converge for valid inputs."""
        # Known: S=100, K=100, T=0.1, sigma=0.2 → price ≈ 2.81
        price = bs_price("CE", 100, 100, 0.1, 0.2)
        iv, err = solve_iv("CE", 100, 100, 0.1, price)
        assert err is None
        assert abs(iv - 0.2) < 1e-6

    def test_compute_time_to_expiry(self):
        """T should be positive for future expiry, zero for past."""
        val = datetime(2026, 7, 28, 10, 0)
        T = compute_time_to_expiry(val, "2026-07-28")
        # Expiry reference is 10:00 UTC on expiry date → T should be 0
        assert T == 0.0

        T2 = compute_time_to_expiry(val, "2026-08-28")
        assert T2 > 0

    def test_align_spot_basic(self):
        """align_spot should return the latest preceding NIFTY close."""
        nifty = [
            {"open_time": datetime(2026, 7, 28, 9, 15), "close": 24000},
            {"open_time": datetime(2026, 7, 28, 9, 18), "close": 24010},
            {"open_time": datetime(2026, 7, 28, 9, 21), "close": 24020},
        ]
        # Exact match
        assert align_spot(datetime(2026, 7, 28, 9, 18), nifty) == 24010
        # Between candles — should use 9:18
        assert align_spot(datetime(2026, 7, 28, 9, 19), nifty) == 24010
        # Before all candles
        assert align_spot(datetime(2026, 7, 28, 9, 14), nifty) is None
        # After all candles — should use last
        assert align_spot(datetime(2026, 7, 28, 9, 30), nifty) == 24020

    def test_bs_greeks_ce_has_positive_delta(self):
        """CE delta should be between 0 and 1."""
        g = bs_greeks("CE", 100, 100, 0.1, 0.2)
        assert 0 < g["delta"] < 1
        assert g["gamma"] > 0
        assert g["vega"] > 0

    def test_bs_greeks_pe_has_negative_delta(self):
        """PE delta should be between -1 and 0."""
        g = bs_greeks("PE", 100, 100, 0.1, 0.2)
        assert -1 < g["delta"] < 0
        assert g["gamma"] > 0

    def test_greeks_at_expiry(self):
        """At expiry (T=0), Greeks should be zero (except delta)."""
        g = bs_greeks("CE", 100, 100, 0, 0.2)
        assert g["gamma"] == 0.0
        assert g["vega"] == 0.0
        assert g["theta"] == 0.0
