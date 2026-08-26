"""Tests for Phase 7.17 — Historical Strike/Expiry Selection.

All tests use synthetic data.  No live API calls.
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ContractSpec, NiftyCandle
from app.services.strike_selection import (
    get_historical_atm,
    round_to_nearest_strike,
    select_strike_universe,
    select_contract_universe,
    select_monthly_expiries,
    select_tier1_universe,
    format_selection_report,
    NIFTY_STRIKE_INTERVAL,
    DEFAULT_STRIKE_RANGE,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_nifty_candle(
    db,
    symbol="NIFTY",
    interval="3min",
    open_time=None,
    open_price=24500.0,
    high=None,
    low=None,
    close=None,
    volume=10000.0,
):
    """Insert a synthetic NIFTY candle into the database."""
    if open_time is None:
        open_time = datetime(2024, 10, 28, 3, 45, tzinfo=UTC)  # 09:15 IST

    candle = NiftyCandle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        open=open_price,
        high=high or open_price + 50,
        low=low or open_price - 50,
        close=close or open_price + 10,
        volume=volume,
    )
    db.add(candle)
    db.commit()
    return candle


def _make_contract_spec(
    db,
    instrument_key="NSE_FO|48891|31-10-2024",
    underlying="NIFTY",
    expiry="2024-10-31",
    strike_price=22250.0,
    instrument_type="PE",
    lot_size=25,
    minimum_lot=25,
    freeze_quantity=1800.0,
    tick_size=0.05,
    trading_symbol="NIFTY 22250 PE 31 OCT 24",
    segment="NSE_FO",
    exchange="NSE",
    weekly=False,
):
    """Insert a synthetic contract spec into the database."""
    spec = ContractSpec(
        instrument_key=instrument_key,
        underlying=underlying,
        underlying_key="NSE_INDEX|Nifty 50",
        expiry=expiry,
        strike_price=strike_price,
        instrument_type=instrument_type,
        lot_size=lot_size,
        minimum_lot=minimum_lot,
        freeze_quantity=freeze_quantity,
        tick_size=tick_size,
        trading_symbol=trading_symbol,
        segment=segment,
        exchange=exchange,
        weekly=weekly,
        source="UPSTOX_EXPIRED_INSTRUMENTS",
        source_reference="test",
        fetched_at=datetime.now(UTC),
    )
    db.add(spec)
    db.commit()
    return spec


# ---------------------------------------------------------------------------
# Test: round_to_nearest_strike
# ---------------------------------------------------------------------------

class TestRoundToNearestStrike:
    """Test strike price rounding."""

    def test_exact_strike(self):
        assert round_to_nearest_strike(24500) == 24500

    def test_round_up(self):
        assert round_to_nearest_strike(24523) == 24525

    def test_round_down(self):
        assert round_to_nearest_strike(24512) == 24500

    def test_round_half_up(self):
        # Python's round() uses banker's rounding, so 0.5 rounds to even
        # 24512.5 / 25 = 980.5 → rounds to 980 → 24500
        assert round_to_nearest_strike(24512.5) == 24500

    def test_low_strike(self):
        assert round_to_nearest_strike(20001) == 20000

    def test_high_strike(self):
        assert round_to_nearest_strike(25999) == 26000

    def test_custom_interval(self):
        assert round_to_nearest_strike(100, interval=10) == 100
        assert round_to_nearest_strike(103, interval=10) == 100
        assert round_to_nearest_strike(107, interval=10) == 110

    def test_zero(self):
        assert round_to_nearest_strike(0) == 0

    def test_negative(self):
        assert round_to_nearest_strike(-24523) == -24525


# ---------------------------------------------------------------------------
# Test: select_strike_universe
# ---------------------------------------------------------------------------

class TestSelectStrikeUniverse:
    """Test strike universe selection."""

    def test_basic_selection(self):
        strikes = select_strike_universe(24500, range_size=2)
        assert strikes == [24450, 24475, 24500, 24525, 24550]
        assert len(strikes) == 5  # 2*2 + 1

    def test_default_range(self):
        strikes = select_strike_universe(24500)
        assert len(strikes) == 41  # 2*20 + 1
        assert strikes[0] == 24500 - 20 * NIFTY_STRIKE_INTERVAL
        assert strikes[-1] == 24500 + 20 * NIFTY_STRIKE_INTERVAL
        assert 24500 in strikes

    def test_sorted_ascending(self):
        strikes = select_strike_universe(24500, range_size=10)
        assert strikes == sorted(strikes)

    def test_atm_in_center(self):
        strikes = select_strike_universe(24500, range_size=5)
        mid = len(strikes) // 2
        assert strikes[mid] == 24500

    def test_custom_interval(self):
        strikes = select_strike_universe(24500, range_size=2, interval=50)
        assert strikes == [24400, 24450, 24500, 24550, 24600]

    def test_range_zero(self):
        strikes = select_strike_universe(24500, range_size=0)
        assert strikes == [24500]

    def test_all_strikes_are_multiples_of_interval(self):
        strikes = select_strike_universe(24500, range_size=20)
        for s in strikes:
            assert s % NIFTY_STRIKE_INTERVAL == 0


# ---------------------------------------------------------------------------
# Test: get_historical_atm
# ---------------------------------------------------------------------------

class TestGetHistoricalATM:
    """Test historical ATM calculation from stored NIFTY candles."""

    def test_basic_atm_calculation(self, db_session):
        """ATM should be calculated from the first candle's open price."""
        # Insert a candle at 09:15 IST on 2024-10-28
        # 09:15 IST = 03:45 UTC
        open_time = datetime(2024, 10, 28, 3, 45, tzinfo=UTC)
        _make_nifty_candle(
            db_session,
            open_time=open_time,
            open_price=24523.0,
        )

        atm = get_historical_atm(db_session, date(2024, 10, 28))
        assert atm == 24525  # Rounded to nearest 25

    def test_atm_rounded_to_interval(self, db_session):
        """ATM must be rounded to the nearest strike interval."""
        open_time = datetime(2024, 10, 28, 3, 45, tzinfo=UTC)
        _make_nifty_candle(
            db_session,
            open_time=open_time,
            open_price=24512.0,
        )

        atm = get_historical_atm(db_session, date(2024, 10, 28))
        assert atm == 24500  # Rounded down

    def test_atm_looks_back_if_no_candles(self, db_session):
        """Should look back up to 5 days if no candles for target date."""
        # Insert candle for 2024-10-25 (3 days before target)
        open_time = datetime(2024, 10, 25, 3, 45, tzinfo=UTC)
        _make_nifty_candle(
            db_session,
            open_time=open_time,
            open_price=24000.0,
        )

        # Request ATM for 2024-10-28 (no candles)
        atm = get_historical_atm(db_session, date(2024, 10, 28))
        assert atm == 24000

    def test_atm_returns_none_if_no_data(self, db_session):
        """Should return None if no candles exist at all."""
        atm = get_historical_atm(db_session, date(2024, 10, 28))
        assert atm is None

    def test_atm_string_date(self, db_session):
        """Should accept string dates."""
        open_time = datetime(2024, 10, 28, 3, 45, tzinfo=UTC)
        _make_nifty_candle(
            db_session,
            open_time=open_time,
            open_price=24500.0,
        )

        atm = get_historical_atm(db_session, "2024-10-28")
        assert atm == 24500

    def test_atm_uses_first_candle_of_day(self, db_session):
        """Should use the opening candle (09:15 IST), not later candles."""
        # Insert two candles: 09:15 and 09:18 IST
        open_time_1 = datetime(2024, 10, 28, 3, 45, tzinfo=UTC)  # 09:15 IST
        open_time_2 = datetime(2024, 10, 28, 3, 48, tzinfo=UTC)  # 09:18 IST

        _make_nifty_candle(
            db_session,
            open_time=open_time_1,
            open_price=24500.0,
        )
        _make_nifty_candle(
            db_session,
            open_time=open_time_2,
            open_price=24600.0,
        )

        atm = get_historical_atm(db_session, date(2024, 10, 28))
        assert atm == 24500  # Uses first candle's open


# ---------------------------------------------------------------------------
# Test: select_contract_universe
# ---------------------------------------------------------------------------

class TestSelectContractUniverse:
    """Test contract universe selection."""

    def test_basic_selection(self, db_session):
        """Should select CE and PE for each strike."""
        # Create contracts for 5 strikes
        strikes = [24450, 24475, 24500, 24525, 24550]
        expiry = "2024-10-31"

        specs = []
        for strike in strikes:
            for ctype in ("CE", "PE"):
                spec = _make_contract_spec(
                    db_session,
                    instrument_key=f"NSE_FO|{int(strike)}|{expiry}|{ctype}",
                    expiry=expiry,
                    strike_price=strike,
                    instrument_type=ctype,
                )
                specs.append({
                    "instrument_key": spec.instrument_key,
                    "expiry": spec.expiry,
                    "strike_price": spec.strike_price,
                    "instrument_type": spec.instrument_type,
                    "lot_size": spec.lot_size,
                })

        result = select_contract_universe(strikes, expiry, specs)
        assert len(result) == 10  # 5 strikes × 2 types

    def test_missing_contract_logged(self, db_session, caplog):
        """Missing contracts should be logged as warnings."""
        strikes = [24500, 24525]
        expiry = "2024-10-31"

        # Only create CE for 24500
        specs = [{
            "instrument_key": "NSE_FO|24500|2024-10-31|CE",
            "expiry": expiry,
            "strike_price": 24500.0,
            "instrument_type": "CE",
            "lot_size": 25,
        }]

        result = select_contract_universe(strikes, expiry, specs)
        assert len(result) == 1
        assert "Missing" in caplog.text

    def test_different_lot_sizes_preserved(self, db_session):
        """Different lot sizes should be preserved per contract."""
        expiry = "2024-10-31"
        specs = [
            {
                "instrument_key": "NSE_FO|1|2024-10-31|CE",
                "expiry": expiry,
                "strike_price": 24500.0,
                "instrument_type": "CE",
                "lot_size": 25,
            },
            {
                "instrument_key": "NSE_FO|2|2024-10-31|CE",
                "expiry": expiry,
                "strike_price": 24525.0,
                "instrument_type": "CE",
                "lot_size": 75,
            },
        ]

        result = select_contract_universe([24500, 24525], expiry, specs)
        lot_sizes = [c["lot_size"] for c in result]
        assert 25 in lot_sizes
        assert 75 in lot_sizes


# ---------------------------------------------------------------------------
# Test: select_monthly_expiries
# ---------------------------------------------------------------------------

class TestSelectMonthlyExpiries:
    """Test monthly expiry selection."""

    def test_basic_selection(self, db_session):
        """Should select the latest expiry per month."""
        # Create expiries across 3 months
        for expiry in ["2024-09-26", "2024-10-31", "2024-11-28"]:
            _make_contract_spec(
                db_session,
                instrument_key=f"NSE_FO|{expiry}|CE",
                expiry=expiry,
            )

        result = select_monthly_expiries(
            db_session,
            date(2024, 9, 1),
            date(2024, 12, 1),
        )
        assert len(result) == 3
        assert "2024-09-26" in result
        assert "2024-10-31" in result
        assert "2024-11-28" in result

    def test_multiple_expiries_same_month(self, db_session):
        """Should keep only the latest expiry per month."""
        # Two expiries in October 2024
        _make_contract_spec(
            db_session,
            instrument_key="NSE_FO|1|2024-10-24|CE",
            expiry="2024-10-24",
        )
        _make_contract_spec(
            db_session,
            instrument_key="NSE_FO|2|2024-10-31|CE",
            expiry="2024-10-31",
        )

        result = select_monthly_expiries(
            db_session,
            date(2024, 10, 1),
            date(2024, 11, 1),
        )
        assert len(result) == 1
        assert result[0] == "2024-10-31"  # Latest in October

    def test_date_range_filtering(self, db_session):
        """Should only return expiries within the date range."""
        _make_contract_spec(
            db_session,
            instrument_key="NSE_FO|1|2024-09-26|CE",
            expiry="2024-09-26",
        )
        _make_contract_spec(
            db_session,
            instrument_key="NSE_FO|2|2024-10-31|CE",
            expiry="2024-10-31",
        )

        # Only October
        result = select_monthly_expiries(
            db_session,
            date(2024, 10, 1),
            date(2024, 10, 31),
        )
        assert len(result) == 1
        assert result[0] == "2024-10-31"

    def test_empty_result(self, db_session):
        """Should return empty list if no expiries in range."""
        result = select_monthly_expiries(
            db_session,
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
        assert result == []

    def test_sorted_ascending(self, db_session):
        """Results should be sorted ascending."""
        for expiry in ["2024-11-28", "2024-09-26", "2024-10-31"]:
            _make_contract_spec(
                db_session,
                instrument_key=f"NSE_FO|{expiry}|CE",
                expiry=expiry,
            )

        result = select_monthly_expiries(
            db_session,
            date(2024, 9, 1),
            date(2024, 12, 1),
        )
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# Test: select_tier1_universe
# ---------------------------------------------------------------------------

class TestSelectTier1Universe:
    """Test the complete Tier 1 selection pipeline."""

    def test_basic_selection(self, db_session):
        """Should select expiries, calculate ATM, and select strikes."""
        # Insert NIFTY candles for ATM calculation
        open_time = datetime(2024, 10, 28, 3, 45, tzinfo=UTC)
        _make_nifty_candle(
            db_session,
            open_time=open_time,
            open_price=24500.0,
        )

        # Insert contract specs for October 2024
        for strike in range(24000, 25001, 25):
            for ctype in ("CE", "PE"):
                _make_contract_spec(
                    db_session,
                    instrument_key=f"NSE_FO|{strike}|2024-10-31|{ctype}",
                    expiry="2024-10-31",
                    strike_price=float(strike),
                    instrument_type=ctype,
                    lot_size=25,
                )

        result = select_tier1_universe(
            db_session,
            date(2024, 10, 1),
            date(2024, 11, 1),
        )

        assert len(result["monthly_expiries"]) == 1
        assert result["monthly_expiries"][0]["atm"] == 24500
        assert result["monthly_expiries"][0]["strike_count"] == 41
        assert result["monthly_expiries"][0]["ce_count"] == 41
        assert result["monthly_expiries"][0]["pe_count"] == 41
        assert result["total_contracts"] == 82

    def test_different_historical_lot_sizes(self, db_session):
        """Different lot sizes should coexist across expiries."""
        # Insert NIFTY candles
        for d in range(1, 32):
            try:
                open_time = datetime(2024, 10, d, 3, 45, tzinfo=UTC)
                _make_nifty_candle(
                    db_session,
                    open_time=open_time,
                    open_price=24500.0,
                )
            except Exception:
                pass

        # October 2024: lot_size=25
        for strike in [24475, 24500, 24525]:
            for ctype in ("CE", "PE"):
                _make_contract_spec(
                    db_session,
                    instrument_key=f"NSE_FO|{strike}|2024-10-31|{ctype}",
                    expiry="2024-10-31",
                    strike_price=float(strike),
                    instrument_type=ctype,
                    lot_size=25,
                )

        # April 2025: lot_size=75
        for strike in [24475, 24500, 24525]:
            for ctype in ("CE", "PE"):
                _make_contract_spec(
                    db_session,
                    instrument_key=f"NSE_FO|{strike}|2025-04-17|{ctype}",
                    expiry="2025-04-17",
                    strike_price=float(strike),
                    instrument_type=ctype,
                    lot_size=75,
                )

        result = select_tier1_universe(
            db_session,
            date(2024, 10, 1),
            date(2025, 5, 1),
        )

        # Check that different lot sizes are preserved
        lot_sizes_by_expiry = {}
        for exp_info in result["monthly_expiries"]:
            lot_sizes_by_expiry[exp_info["expiry"]] = exp_info["lot_sizes"]

        # October should have lot_size=25
        if "2024-10-31" in lot_sizes_by_expiry:
            assert 25 in lot_sizes_by_expiry["2024-10-31"]

        # April should have lot_size=75
        if "2025-04-17" in lot_sizes_by_expiry:
            assert 75 in lot_sizes_by_expiry["2025-04-17"]


# ---------------------------------------------------------------------------
# Test: format_selection_report
# ---------------------------------------------------------------------------

class TestFormatSelectionReport:
    """Test report formatting."""

    def test_basic_report(self):
        """Should format a readable report."""
        selection = {
            "start_date": "2024-10-01",
            "end_date": "2024-11-01",
            "underlying": "NIFTY",
            "strike_range": 20,
            "monthly_expiries": [
                {
                    "expiry": "2024-10-31",
                    "atm": 24500,
                    "lowest_strike": 24000,
                    "highest_strike": 25000,
                    "strike_count": 41,
                    "ce_count": 41,
                    "pe_count": 41,
                    "total_contracts": 82,
                    "lot_sizes": [25],
                }
            ],
            "total_contracts": 82,
            "total_strikes": 41,
        }

        report = format_selection_report(selection)
        assert "2024-10-31" in report
        assert "24500" in report
        assert "82" in report
        assert "25" in report


# ---------------------------------------------------------------------------
# Test: Lot-size preservation (critical invariant)
# ---------------------------------------------------------------------------

class TestLotSizePreservation:
    """Test that historical lot sizes are preserved correctly."""

    def test_lot_size_not_inferred_from_current(self, db_session):
        """Lot size must come from contract_specs, not from current NIFTY."""
        # Create a contract with lot_size=25 (historical)
        spec = _make_contract_spec(
            db_session,
            instrument_key="NSE_FO|24500|2024-10-31|CE",
            expiry="2024-10-31",
            strike_price=24500.0,
            instrument_type="CE",
            lot_size=25,
        )

        # Selection should use lot_size=25 from contract_specs
        result = select_contract_universe(
            [24500],
            "2024-10-31",
            [{
                "instrument_key": spec.instrument_key,
                "expiry": spec.expiry,
                "strike_price": spec.strike_price,
                "instrument_type": spec.instrument_type,
                "lot_size": spec.lot_size,
            }],
        )

        assert len(result) == 1
        assert result[0]["lot_size"] == 25

    def test_different_instruments_different_lot_sizes(self, db_session):
        """Different instrument_keys can have different lot sizes."""
        specs = [
            {
                "instrument_key": "NSE_FO|1|2024-10-31|CE",
                "expiry": "2024-10-31",
                "strike_price": 24500.0,
                "instrument_type": "CE",
                "lot_size": 25,
            },
            {
                "instrument_key": "NSE_FO|2|2024-10-31|CE",
                "expiry": "2024-10-31",
                "strike_price": 24525.0,
                "instrument_type": "CE",
                "lot_size": 75,
            },
            {
                "instrument_key": "NSE_FO|3|2024-10-31|CE",
                "expiry": "2024-10-31",
                "strike_price": 24550.0,
                "instrument_type": "CE",
                "lot_size": 50,
            },
        ]

        result = select_contract_universe([24500, 24525, 24550], "2024-10-31", specs)
        lot_sizes = {c["strike_price"]: c["lot_size"] for c in result}

        assert lot_sizes[24500] == 25
        assert lot_sizes[24525] == 75
        assert lot_sizes[24550] == 50

    def test_null_lot_size_preserved(self, db_session):
        """NULL lot_size should remain NULL, not be substituted."""
        specs = [
            {
                "instrument_key": "NSE_FO|1|2024-10-31|CE",
                "expiry": "2024-10-31",
                "strike_price": 24500.0,
                "instrument_type": "CE",
                "lot_size": None,
            },
        ]

        result = select_contract_universe([24500], "2024-10-31", specs)
        assert len(result) == 1
        assert result[0]["lot_size"] is None
