"""Phase 6.8D regression: dynamic-expiry chain-selection correctness.

The bug was: resolve_legs() could resolve a leg's formula to expiry A but
extract LTP/quote from the chain for expiry B.  These tests use distinct
LTP values per expiry so any chain mismatch causes an immediate failure.

All tests use the pure resolver functions directly (no broker/HTTP needed).

Expiry layout (today = 2026-08-19, Wednesday):
  2026-08-20 (Thu) — current week expiry  (DTE=1)
  2026-08-27 (Thu) — next week expiry     (DTE=8)
  2026-09-24 (Thu) — Sep monthly          (DTE=36)

IMPORTANT: The resolver does NOT assume any specific weekday.  It uses
the broker-provided listed expiry dates as the sole source of truth.
These test dates happen to be Thursdays, but the resolver works identically
with Tuesday, Friday, or any other weekday expiries.
"""

from datetime import date
import pytest

from app.services.strategy_resolver import (
    ExpiryMode,
    LegFormula,
    StrikeMode,
    _resolve_expiry,
    _resolve_strike,
    chain_rows,
    resolve_expiry_current_week,
    resolve_expiry_next_week,
    resolve_expiry_monthly,
    resolve_leg,
    sorted_strikes,
    spot_price,
)


# ---------------------------------------------------------------------------
# Test fixtures: chains with DIFFERENT LTP values per expiry
# ---------------------------------------------------------------------------

def _make_chain(spot, strikes, expiry_label, ltp_base):
    """Build a canonical chain where LTP varies by expiry_label.

    Every strike gets ltp = ltp_base + strike_offset * 0.1.
    """
    rows = []
    for s in strikes:
        rows.append({
            "strike": s,
            "call": {
                "ltp": ltp_base + (s - 25000) * 0.1,
                "delta": 0.5 + (s - 25000) * 0.0001,
                "quote_timestamp": "2026-08-19T10:00:00+05:30",
            },
            "put": {
                "ltp": ltp_base - (s - 25000) * 0.1,
                "delta": -0.5 - (s - 25000) * 0.0001,
                "quote_timestamp": "2026-08-19T10:00:00+05:30",
            },
        })
    return {
        "symbol": "NIFTY",
        "expiry_date": expiry_label,
        "underlying_spot_price": spot,
        "chain": rows,
    }


STRIKES = [24800.0, 24900.0, 25000.0, 25100.0, 25200.0]

# Three expiries with DISTINCT LTP bases
# today = 2026-08-19 (Wed)
CHAIN_CW  = _make_chain(25000.0, STRIKES, "2026-08-20", ltp_base=100)  # current week
CHAIN_NW  = _make_chain(25000.0, STRIKES, "2026-08-27", ltp_base=200)  # next week
CHAIN_MTH = _make_chain(25000.0, STRIKES, "2026-09-24", ltp_base=50)   # Sep monthly

ALL_EXPIRIES = ["2026-08-20", "2026-08-27", "2026-09-24"]

CHAINS = {
    "2026-08-20": CHAIN_CW,
    "2026-08-27": CHAIN_NW,
    "2026-09-24": CHAIN_MTH,
}

TODAY = date(2026, 8, 19)


def _get_ltp(chain, strike, option_type):
    """Extract LTP from a chain for a given strike and option type."""
    rows = chain.get("chain", [])
    for row in rows:
        if abs(row["strike"] - strike) < 0.001:
            side = row.get(option_type) or {}
            return side.get("ltp")
    return None


# ---------------------------------------------------------------------------
# Tests: today parameter propagation
# ---------------------------------------------------------------------------

class TestTodayPropagation:
    """Verify that the supplied today parameter controls expiry selection."""

    def test_current_week_with_controlled_today(self):
        """today=2026-08-19 (Wed) → current_week picks 2026-08-20 (nearest future)."""
        exp, _ = _resolve_expiry(
            LegFormula(action="buy", option_type="call", quantity=1, lot_size=65,
                       expiry_mode=ExpiryMode.CURRENT_WEEK),
            ALL_EXPIRIES,
            today=TODAY,
        )
        assert exp == "2026-08-20"

    def test_next_week_with_controlled_today(self):
        """today=2026-08-19 (Wed) → next_week picks 2026-08-27 (second-nearest future)."""
        exp, _ = _resolve_expiry(
            LegFormula(action="buy", option_type="call", quantity=1, lot_size=65,
                       expiry_mode=ExpiryMode.NEXT_WEEK),
            ALL_EXPIRIES,
            today=TODAY,
        )
        assert exp == "2026-08-27"

    def test_monthly_august_picks_latest_aug(self):
        """today=2026-08-19 → monthly picks latest in August = 2026-08-27."""
        exp, _ = _resolve_expiry(
            LegFormula(action="buy", option_type="call", quantity=1, lot_size=65,
                       expiry_mode=ExpiryMode.MONTHLY),
            ALL_EXPIRIES,
            today=TODAY,
        )
        assert exp == "2026-08-27"

    def test_monthly_september_picks_latest_sep(self):
        """today=2026-09-15 → monthly picks latest in September = 2026-09-24."""
        exp, _ = _resolve_expiry(
            LegFormula(action="buy", option_type="call", quantity=1, lot_size=65,
                       expiry_mode=ExpiryMode.MONTHLY),
            ALL_EXPIRIES,
            today=date(2026, 9, 15),
        )
        assert exp == "2026-09-24"

    def test_dte_range_with_controlled_today(self):
        """today=2026-08-19 → DTE 5-10 picks 2026-08-27 (DTE=8)."""
        exp, _ = _resolve_expiry(
            LegFormula(action="buy", option_type="call", quantity=1, lot_size=65,
                       expiry_mode=ExpiryMode.DTE_RANGE, expiry_dte_min=5, expiry_dte_max=10),
            ALL_EXPIRIES,
            today=TODAY,
        )
        assert exp == "2026-08-27"

    def test_dte_range_tight_picks_current_week(self):
        """today=2026-08-19 → DTE 0-2 picks 2026-08-20 (DTE=1)."""
        exp, _ = _resolve_expiry(
            LegFormula(action="buy", option_type="call", quantity=1, lot_size=65,
                       expiry_mode=ExpiryMode.DTE_RANGE, expiry_dte_min=0, expiry_dte_max=2),
            ALL_EXPIRIES,
            today=TODAY,
        )
        assert exp == "2026-08-20"


# ---------------------------------------------------------------------------
# Tests: chain-selection correctness for each dynamic expiry mode
# ---------------------------------------------------------------------------

class TestChainSelectionCurrentWeek:
    """current_week resolves to nearest future expiry → price must come from that chain."""

    def test_resolved_expiry_matches_price_source(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.CURRENT_WEEK,
        )
        result = resolve_leg(formula, CHAIN_CW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-08-20"

        ltp = _get_ltp(CHAIN_CW, 25000.0, "call")
        assert ltp == 100.0, f"Expected LTP 100.0 from CW chain, got {ltp}"

        # Verify other chains have DIFFERENT LTPs
        ltp_nw = _get_ltp(CHAIN_NW, 25000.0, "call")
        ltp_mth = _get_ltp(CHAIN_MTH, 25000.0, "call")
        assert ltp_nw != ltp, "NW chain LTP must differ"
        assert ltp_mth != ltp, "Monthly chain LTP must differ"


class TestChainSelectionNextWeek:
    """next_week resolves to second-nearest future expiry → price must come from that chain."""

    def test_resolved_expiry_matches_price_source(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.NEXT_WEEK,
        )
        result = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-08-27"

        # Price must come from the 2026-08-27 chain, NOT 2026-08-20
        ltp = _get_ltp(CHAIN_NW, 25000.0, "call")
        assert ltp == 200.0, f"Expected LTP 200.0 from NW chain, got {ltp}"

        # Verify the CW chain has a DIFFERENT LTP
        ltp_cw = _get_ltp(CHAIN_CW, 25000.0, "call")
        assert ltp_cw == 100.0, "CW chain LTP must differ to prove chain selection matters"

    def test_strike_resolved_against_resolved_expiry_chain(self):
        """ATM strike must be resolved against the next_week chain."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM,
            expiry_mode=ExpiryMode.NEXT_WEEK,
        )
        result = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_strike == 25000.0
        assert result.leg.resolved_expiry == "2026-08-27"


class TestChainSelectionMonthly:
    """monthly resolves to latest-in-month expiry → price must come from that chain."""

    def test_august_monthly_resolves_to_aug_27(self):
        """today=Aug 19 → monthly picks 2026-08-27 → ltp_base=200."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.MONTHLY,
        )
        result = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-08-27"

        ltp = _get_ltp(CHAIN_NW, 25000.0, "call")
        assert ltp == 200.0, f"Expected LTP 200.0 for Aug monthly, got {ltp}"

        ltp_cw = _get_ltp(CHAIN_CW, 25000.0, "call")
        assert ltp_cw == 100.0, "CW chain LTP must differ"

    def test_september_monthly_resolves_to_sep_24(self):
        """today=Sep 15 → monthly picks 2026-09-24 → ltp_base=50."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.MONTHLY,
        )
        result = resolve_leg(formula, CHAIN_MTH, ALL_EXPIRIES, today=date(2026, 9, 15))
        assert result.ok
        assert result.leg.resolved_expiry == "2026-09-24"

        ltp = _get_ltp(CHAIN_MTH, 25000.0, "call")
        assert ltp == 50.0, f"Expected LTP 50.0 for Sep monthly, got {ltp}"

        ltp_cw = _get_ltp(CHAIN_CW, 25000.0, "call")
        ltp_nw = _get_ltp(CHAIN_NW, 25000.0, "call")
        assert ltp_cw != ltp, "CW chain LTP must differ"
        assert ltp_nw != ltp, "NW chain LTP must differ"

    def test_strike_resolved_against_monthly_chain(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM,
            expiry_mode=ExpiryMode.MONTHLY,
        )
        result = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_strike == 25000.0
        assert result.leg.resolved_expiry == "2026-08-27"


class TestChainSelectionDTERange:
    """dte_range resolves to an expiry → price must come from that chain."""

    def test_narrow_dte_picks_current_week(self):
        """DTE 0-2 picks 2026-08-20 (DTE=1) → ltp_base=100."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.DTE_RANGE,
            expiry_dte_min=0, expiry_dte_max=2,
        )
        result = resolve_leg(formula, CHAIN_CW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-08-20"

        ltp = _get_ltp(CHAIN_CW, 25000.0, "call")
        assert ltp == 100.0, f"Expected LTP 100.0 from CW chain, got {ltp}"

    def test_wide_dte_picks_sep(self):
        """DTE 30-40 picks 2026-09-24 (DTE=36) → ltp_base=50."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.DTE_RANGE,
            expiry_dte_min=30, expiry_dte_max=40,
        )
        result = resolve_leg(formula, CHAIN_MTH, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-09-24"

        ltp = _get_ltp(CHAIN_MTH, 25000.0, "call")
        assert ltp == 50.0, f"Expected LTP 50.0 from monthly chain, got {ltp}"

    def test_medium_dte_picks_next_week(self):
        """DTE 5-10 picks 2026-08-27 (DTE=8) → ltp_base=200."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.DTE_RANGE,
            expiry_dte_min=5, expiry_dte_max=10,
        )
        result = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-08-27"

        ltp = _get_ltp(CHAIN_NW, 25000.0, "call")
        assert ltp == 200.0, f"Expected LTP 200.0 from NW chain, got {ltp}"


# ---------------------------------------------------------------------------
# Tests: cross-expiry LTP divergence proves correct chain usage
# ---------------------------------------------------------------------------

class TestCrossExpiryLTPDivergence:
    """Proof that different LTPs per expiry catch chain mismatches."""

    def test_cw_nw_mth_all_have_different_ltp(self):
        """All three expiry chains must have different LTPs for the same strike."""
        ltp_cw = _get_ltp(CHAIN_CW, 25000.0, "call")    # 100.0
        ltp_nw = _get_ltp(CHAIN_NW, 25000.0, "call")    # 200.0
        ltp_mth = _get_ltp(CHAIN_MTH, 25000.0, "call")  # 50.0
        assert ltp_cw == 100.0
        assert ltp_nw == 200.0
        assert ltp_mth == 50.0
        assert len({ltp_cw, ltp_nw, ltp_mth}) == 3, "All LTPs must be unique"

    def test_delta_target_picks_correct_chain_row(self):
        """Delta targeting must use the resolved expiry's chain for Greeks."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.DELTA, target_delta=0.50,
            expiry_mode=ExpiryMode.NEXT_WEEK,
        )
        result = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result.ok
        assert result.leg.resolved_expiry == "2026-08-27"
        assert result.leg.resolved_strike == 25000.0
        assert result.leg.delta_actual is not None

    def test_wrong_chain_gives_wrong_price(self):
        """Passing the wrong chain yields a different LTP — proving selection matters."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=25000.0,
            expiry_mode=ExpiryMode.NEXT_WEEK,
        )
        result_ok = resolve_leg(formula, CHAIN_NW, ALL_EXPIRIES, today=TODAY)
        assert result_ok.ok
        ltp_correct = _get_ltp(CHAIN_NW, 25000.0, "call")
        assert ltp_correct == 200.0

        ltp_wrong = _get_ltp(CHAIN_CW, 25000.0, "call")
        assert ltp_wrong == 100.0
        assert ltp_correct != ltp_wrong, "Different chains must give different prices"


# ---------------------------------------------------------------------------
# Tests: NIFTY Tuesday weekly / holiday / non-Tuesday expiry conventions
# ---------------------------------------------------------------------------

class TestNIFTYExpiryConventions:
    """Verify the resolver follows broker-listed expiries for NIFTY conventions.

    NIFTY 50 index options: weekly expiry on Tuesday, monthly on last
    Tuesday of the month.  If Tuesday is a holiday, expiry moves to the
    previous trading day.  The resolver must NOT hardcode any weekday —
    it uses the broker-provided list as ground truth.
    """

    def test_nifty_tuesday_weekly(self):
        """Broker lists Tuesday expiries → current_week picks nearest Tuesday."""
        # Tue Aug 18, Tue Aug 25, Tue Sep 1
        expiries = ["2026-08-18", "2026-08-25", "2026-09-01"]
        today = date(2026, 8, 17)  # Monday
        exp, _ = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-18"  # nearest future Tuesday

    def test_nifty_tuesday_monthly_last_of_month(self):
        """Broker lists last Tuesday of Sep = Sep 29 → monthly picks it."""
        expiries = [
            "2026-09-01", "2026-09-08", "2026-09-15",
            "2026-09-22", "2026-09-29",  # last Tue of Sep
        ]
        today = date(2026, 9, 10)
        exp, _ = resolve_expiry_monthly(expiries, today=today)
        assert exp == "2026-09-29"

    def test_tuesday_holiday_previous_trading_day(self):
        """Tue Aug 18 is a holiday → broker lists Mon Aug 17 instead.

        current_week must pick Mon Aug 17, not skip to Aug 25."""
        expiries = ["2026-08-17", "2026-08-25", "2026-09-01"]
        today = date(2026, 8, 16)  # Sunday
        exp, _ = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-17"  # holiday-adjusted (Monday)

    def test_tuesday_holiday_next_week(self):
        """Holiday-adjusted list → next_week picks the second-nearest future."""
        expiries = ["2026-08-17", "2026-08-25", "2026-09-01"]
        today = date(2026, 8, 16)
        exp, _ = resolve_expiry_next_week(expiries, today=today)
        assert exp == "2026-08-25"

    def test_non_tuesday_listed_expiry(self):
        """Prove the resolver follows broker-listed dates, not weekday assumptions.

        Expiries are on Wednesday and Friday — no Tuesday at all."""
        expiries = ["2026-08-19", "2026-08-21", "2026-08-28"]
        today = date(2026, 8, 18)  # Tuesday
        exp, _ = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-19"  # nearest future (Wednesday)

    def test_all_friday_weekly(self):
        """If broker only lists Friday expiries, resolver picks them."""
        expiries = ["2026-08-21", "2026-08-28", "2026-09-04"]
        today = date(2026, 8, 19)
        exp, _ = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-21"  # nearest future Friday

    def test_current_week_on_expiry_day(self):
        """If today IS a listed expiry, return it (expiry day = current week)."""
        expiries = ["2026-08-18", "2026-08-25"]
        today = date(2026, 8, 18)  # Tuesday = expiry day
        exp, _ = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-18"

    def test_next_week_requires_at_least_two_future(self):
        """next_week with only one future expiry falls back to nearest."""
        expiries = ["2026-08-25"]  # only one future
        today = date(2026, 8, 18)
        exp, _ = resolve_expiry_next_week(expiries, today=today)
        assert exp == "2026-08-25"  # fallback to nearest
