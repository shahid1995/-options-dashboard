"""Phase 7.23A — Historical NIFTY Index Coverage and Spot Alignment Tests.

Synthetic tests that verify the spot alignment architecture without requiring
live API calls or the production database.
"""

from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta, timezone

from app.services.historical_greeks import (
    align_spot,
    compute_time_to_expiry,
    bs_price,
    bs_greeks,
    solve_iv,
    bs_intrinsic,
)
from app.services.strike_selection import (
    round_to_nearest_strike,
    select_strike_universe,
    get_historical_atm,
)
from app.services.candle_config import (
    INDEX_MARKET_CLOSE_IST,
    OPTION_MARKET_CLOSE_IST,
    MARKET_OPEN_IST,
    INDEX_CANDLES_PER_TRADING_DAY,
    OPTION_CANDLES_PER_TRADING_DAY,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# 1. Historical ATM calculation
# ---------------------------------------------------------------------------

class TestHistoricalATM:
    """Verify ATM is calculated from historical NIFTY data, never current price."""

    def test_round_to_nearest_strike_25(self):
        """NIFTY strikes are in 25-point intervals."""
        assert round_to_nearest_strike(24523) == 24525
        assert round_to_nearest_strike(24512) == 24500
        assert round_to_nearest_strike(24500) == 24500
        assert round_to_nearest_strike(24537) == 24525

    def test_strike_universe_symmetric(self):
        """ATM ± 20 produces 41 strikes."""
        strikes = select_strike_universe(24500, range_size=20)
        assert len(strikes) == 41
        assert strikes[0] == 24000  # ATM - 20*25
        assert strikes[20] == 24500  # ATM
        assert strikes[40] == 25000  # ATM + 20*25

    def test_strike_universe_sorted(self):
        """Strikes must be in ascending order."""
        strikes = select_strike_universe(24500, range_size=5)
        assert strikes == sorted(strikes)

    def test_no_current_price_fallback(self):
        """The ATM function returns None when no historical data exists,
        never the current price."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import Base

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        # Empty database — no NIFTY candles
        atm = get_historical_atm(db, date(2026, 8, 18), symbol="NIFTY")
        assert atm is None  # Must NOT return a current price

        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# 2. Spot alignment — latest preceding index candle
# ---------------------------------------------------------------------------

class TestSpotAlignment:
    """Verify align_spot uses the latest preceding NIFTY candle."""

    def _make_candles(self, times_and_closes):
        """Create synthetic index candles from (datetime, close) pairs."""
        return [
            {"open_time": t, "close": c}
            for t, c in times_and_closes
        ]

    def test_exact_timestamp_match(self):
        """Option candle at exact index timestamp uses that candle's close."""
        idx_time = datetime(2026, 8, 18, 3, 45)  # 09:15 IST
        candles = self._make_candles([
            (datetime(2026, 8, 18, 3, 45), 25000.0),
            (datetime(2026, 8, 18, 3, 48), 25010.0),
        ])
        spot = align_spot(idx_time, candles)
        assert spot == 25000.0

    def test_between_two_candles(self):
        """Option candle between two index candles uses the earlier one."""
        candles = self._make_candles([
            (datetime(2026, 8, 18, 3, 45), 25000.0),
            (datetime(2026, 8, 18, 3, 48), 25010.0),
            (datetime(2026, 8, 18, 3, 51), 25020.0),
        ])
        # Option at 3:46 — between 3:45 and 3:48
        spot = align_spot(datetime(2026, 8, 18, 3, 46), candles)
        assert spot == 25000.0

    def test_after_all_candles(self):
        """Option candle after all index candles uses the last one."""
        candles = self._make_candles([
            (datetime(2026, 8, 18, 3, 45), 25000.0),
            (datetime(2026, 8, 18, 9, 54), 25500.0),  # 15:24 IST
        ])
        # Option at 15:35 IST = 10:05 UTC
        spot = align_spot(datetime(2026, 8, 18, 10, 5), candles)
        assert spot == 25500.0

    def test_post_close_option_uses_15_27_close(self):
        """Option candle at 15:35 IST uses the 15:27 IST index close."""
        # 15:27 IST = 09:57 UTC
        # 15:35 IST = 10:05 UTC
        candles = self._make_candles([
            (datetime(2026, 8, 18, 3, 45), 25000.0),
            (datetime(2026, 8, 18, 9, 54), 25480.0),
            (datetime(2026, 8, 18, 9, 57), 25500.0),  # 15:27 IST — last index candle
        ])
        spot = align_spot(datetime(2026, 8, 18, 10, 5), candles)
        assert spot == 25500.0

    def test_no_future_candle_selected(self):
        """The alignment must never select a candle after the option timestamp."""
        candles = self._make_candles([
            (datetime(2026, 8, 18, 3, 45), 25000.0),
            (datetime(2026, 8, 18, 10, 0), 25500.0),  # After option time
        ])
        # Option at 9:50 UTC
        spot = align_spot(datetime(2026, 8, 18, 9, 50), candles)
        assert spot == 25000.0  # Must NOT be 25500.0

    def test_empty_candles_returns_none(self):
        """No index candles → spot is None."""
        spot = align_spot(datetime(2026, 8, 18, 9, 50), [])
        assert spot is None

    def test_zero_close_skipped(self):
        """Index candle with close=0 is skipped (invalid)."""
        candles = self._make_candles([
            (datetime(2026, 8, 18, 3, 42), 24990.0),
            (datetime(2026, 8, 18, 3, 45), 0.0),
            (datetime(2026, 8, 18, 3, 48), 25010.0),
        ])
        # Option at 3:46 — skips 0.0 candle, but 3:48 is after option time
        spot = align_spot(datetime(2026, 8, 18, 3, 46), candles)
        assert spot == 24990.0  # Last valid close before option time


# ---------------------------------------------------------------------------
# 3. Trading hours
# ---------------------------------------------------------------------------

class TestTradingHours:
    """Verify trading session constants are correct."""

    def test_index_market_close(self):
        assert INDEX_MARKET_CLOSE_IST == "15:27"

    def test_option_market_close(self):
        assert OPTION_MARKET_CLOSE_IST == "15:40"

    def test_market_open(self):
        assert MARKET_OPEN_IST == "09:15"

    def test_index_candles_per_day(self):
        assert INDEX_CANDLES_PER_TRADING_DAY == 124

    def test_option_candles_per_day(self):
        assert OPTION_CANDLES_PER_TRADING_DAY == 128

    def test_option_session_longer_than_index(self):
        """Options trade 13 minutes longer than the index."""
        assert OPTION_CANDLES_PER_TRADING_DAY > INDEX_CANDLES_PER_TRADING_DAY


# ---------------------------------------------------------------------------
# 4. Time-to-expiry
# ---------------------------------------------------------------------------

class TestTimeToExpiry:
    """Verify T calculation uses calendar days / 365.25."""

    def test_one_year(self):
        """One year → T ≈ 1.0."""
        valuation = datetime(2026, 8, 18, 3, 45, tzinfo=timezone.utc)
        expiry = "2027-08-18"
        T = compute_time_to_expiry(valuation, expiry)
        assert 0.99 < T < 1.01

    def test_same_day_small_positive(self):
        """Same calendar day but before 15:30 IST → small positive T."""
        valuation = datetime(2026, 8, 18, 3, 45, tzinfo=timezone.utc)
        expiry = "2026-08-18"
        T = compute_time_to_expiry(valuation, expiry)
        assert 0.0 <= T < 0.001  # Very small but positive

    def test_past_expiry(self):
        """Past expiry → T = 0 (not negative)."""
        valuation = datetime(2026, 8, 18, 3, 45, tzinfo=timezone.utc)
        expiry = "2026-08-01"
        T = compute_time_to_expiry(valuation, expiry)
        assert T == 0.0


# ---------------------------------------------------------------------------
# 5. Black-Scholes and Greeks consistency
# ---------------------------------------------------------------------------

class TestBlackScholesConsistency:
    """Verify BS pricing and Greeks are mathematically consistent."""

    def test_put_call_parity(self):
        """C - P = S - K*e^(-rT) for European options."""
        S, K, T, sigma, r = 25000, 25000, 0.1, 0.18, 0.065
        call = bs_price("CE", S, K, T, sigma, r)
        put = bs_price("PE", S, K, T, sigma, r)
        parity_lhs = call - put
        parity_rhs = S - K * (2.71828 ** (-r * T))
        assert abs(parity_lhs - parity_rhs) < 1.0  # Within ₹1

    def test_delta_bounds(self):
        """CE delta in (0, 1), PE delta in (-1, 0)."""
        greeks_ce = bs_greeks("CE", 25000, 25000, 0.1, 0.18)
        greeks_pe = bs_greeks("PE", 25000, 25000, 0.1, 0.18)
        assert 0 < greeks_ce["delta"] < 1
        assert -1 < greeks_pe["delta"] < 0

    def test_gamma_positive(self):
        """Gamma is always positive."""
        greeks = bs_greeks("CE", 25000, 25000, 0.1, 0.18)
        assert greeks["gamma"] > 0

    def test_vega_positive(self):
        """Vega is always positive."""
        greeks = bs_greeks("CE", 25000, 25000, 0.1, 0.18)
        assert greeks["vega"] > 0

    def test_ce_delta_larger_than_pe_delta(self):
        """For ATM, CE delta > |PE delta| (both positive, CE closer to 0.5)."""
        greeks_ce = bs_greeks("CE", 25000, 25000, 0.1, 0.18)
        greeks_pe = bs_greeks("PE", 25000, 25000, 0.1, 0.18)
        assert greeks_ce["delta"] > abs(greeks_pe["delta"])


# ---------------------------------------------------------------------------
# 6. IV solver
# ---------------------------------------------------------------------------

class TestIVSolver:
    """Verify IV solver round-trips correctly."""

    def test_known_price_roundtrip(self):
        """Generate price from known IV, recover it."""
        S, K, T, sigma_true, r = 25000, 25000, 0.1, 0.18, 0.065
        price = bs_price("CE", S, K, T, sigma_true, r)
        iv_recovered, err = solve_iv("CE", S, K, T, price, r)
        assert err is None
        assert abs(iv_recovered - sigma_true) < 1e-6

    def test_itm_call(self):
        """ITM call should solve correctly."""
        S, K, T, sigma_true, r = 25000, 24000, 0.1, 0.18, 0.065
        price = bs_price("CE", S, K, T, sigma_true, r)
        iv_recovered, err = solve_iv("CE", S, K, T, price, r)
        assert err is None
        assert abs(iv_recovered - sigma_true) < 1e-6

    def test_otm_put(self):
        """OTM put should solve correctly."""
        S, K, T, sigma_true, r = 25000, 24000, 0.1, 0.18, 0.065
        price = bs_price("PE", S, K, T, sigma_true, r)
        iv_recovered, err = solve_iv("PE", S, K, T, price, r)
        assert err is None
        assert abs(iv_recovered - sigma_true) < 1e-6

    def test_zero_price_returns_error(self):
        """Zero market price → error."""
        iv, err = solve_iv("CE", 25000, 25000, 0.1, 0.0)
        assert iv is None
        assert err is not None

    def test_negative_price_returns_error(self):
        """Negative market price → error."""
        iv, err = solve_iv("CE", 25000, 25000, 0.1, -100.0)
        assert iv is None
        assert err is not None

    def test_expired_option_returns_error(self):
        """T=0 → error."""
        iv, err = solve_iv("CE", 25000, 25000, 0.0, 100.0)
        assert iv is None
        assert err is not None


# ---------------------------------------------------------------------------
# 7. Raw data immutability
# ---------------------------------------------------------------------------

class TestRawDataImmutability:
    """Verify that the Greeks engine does not modify raw candle data."""

    def test_greeks_calculation_is_pure(self):
        """calculate_greeks_for_candle does not take a database session."""
        from app.services.historical_greeks import calculate_greeks_for_candle
        import inspect
        sig = inspect.signature(calculate_greeks_for_candle)
        # The function should NOT have a 'db' or 'session' parameter
        param_names = list(sig.parameters.keys())
        assert "db" not in param_names
        assert "session" not in param_names
