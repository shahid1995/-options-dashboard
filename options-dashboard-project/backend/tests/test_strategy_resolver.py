"""Phase 6.8A: Comprehensive tests for the dynamic strategy resolver."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.strategy_resolver import (
    ExpiryMode,
    LegFormula,
    ResolverResult,
    ResolvedLeg,
    StrikeMode,
    chain_row_by_strike,
    chain_rows,
    nearest_strike_index,
    resolve_atm,
    resolve_atm_offset,
    resolve_atm_offset_steps,
    resolve_delta_target,
    resolve_expiry_current_week,
    resolve_expiry_dte_range,
    resolve_expiry_fixed,
    resolve_expiry_monthly,
    resolve_expiry_next_week,
    resolve_fixed_strike,
    resolve_leg,
    resolve_spot_offset,
    sorted_strikes,
    spot_price,
)


# ============================================================================
# Test fixtures
# ============================================================================

def _chain_row(strike, call_delta=None, put_delta=None, call_ltp=None, put_ltp=None,
               call_oi=1000, put_oi=1000):
    """Build a minimal canonical chain row."""
    return {
        "strike": strike,
        "call": {
            "ltp": call_ltp, "delta": call_delta, "oi": call_oi,
            "volume": 500, "iv": 20.0, "theta": -0.5, "gamma": 0.01,
            "vega": 0.3, "pop": 0.5, "chg_oi": None, "quote_timestamp": None,
        },
        "put": {
            "ltp": put_ltp, "delta": put_delta, "oi": put_oi,
            "volume": 400, "iv": 21.0, "theta": -0.6, "gamma": 0.01,
            "vega": 0.3, "pop": 0.5, "chg_oi": None, "quote_timestamp": None,
        },
    }


def _chain_response(strikes, spot, call_delta=None, put_delta=None):
    """Build a canonical chain response with NIFTY-like structure."""
    rows = []
    for s in strikes:
        # Simulate realistic delta distribution
        if call_delta is not None:
            cd = call_delta
            pd = put_delta if put_delta is not None else call_delta - 1.0
        else:
            # ATM-ish delta distribution
            diff = s - spot
            cd = max(0.01, min(0.99, 0.5 + diff / 2000))
            pd = cd - 1.0
        rows.append(_chain_row(s, call_delta=cd, put_delta=pd, call_ltp=100, put_ltp=80))
    return {
        "symbol": "NIFTY",
        "expiry_date": "2026-08-27",
        "underlying_spot_price": spot,
        "chain": rows,
    }


NIFTY_STRIKES = [24500, 24600, 24700, 24800, 24900, 25000, 25100, 25200, 25300, 25400, 25500]
NIFTY_SPOT = 25030.0

NIFTY_EXPIRIES = [
    "2026-08-20",  # current week (Tue, Aug 20)
    "2026-08-27",  # next week (Tue, Aug 27)
    "2026-09-03",  # week after
    "2026-09-24",  # monthly (last Tue of Sep)
]


# ============================================================================
# 1. Chain helper tests
# ============================================================================

class TestChainHelpers:
    def test_sorted_strikes(self):
        rows = [_chain_row(25100), _chain_row(24900), _chain_row(25000)]
        assert sorted_strikes(rows) == [24900, 25000, 25100]

    def test_sorted_strikes_empty(self):
        assert sorted_strikes([]) == []

    def test_chain_row_by_strike(self):
        rows = [_chain_row(24900), _chain_row(25000)]
        mapping = chain_row_by_strike(rows)
        assert 25000 in mapping
        assert mapping[24900]["strike"] == 24900

    def test_spot_price(self):
        resp = _chain_response(NIFTY_STRIKES, 25030)
        assert spot_price(resp) == 25030.0

    def test_spot_price_missing(self):
        assert spot_price({}) is None

    def test_chain_rows(self):
        resp = _chain_response(NIFTY_STRIKES, 25030)
        assert len(chain_rows(resp)) == len(NIFTY_STRIKES)

    def test_chain_rows_empty(self):
        assert chain_rows({}) == []


# ============================================================================
# 2. nearest_strike_index
# ============================================================================

class TestNearestStrikeIndex:
    def test_exact_match(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert nearest_strike_index(strikes, 25000) == 2

    def test_between_strikes(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert nearest_strike_index(strikes, 25030) == 2  # 25000 closer than 25100

    def test_between_strikes_closer_to_upper(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert nearest_strike_index(strikes, 25070) == 3  # 25100 closer

    def test_equidistant_picks_lower(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert nearest_strike_index(strikes, 25050) == 2  # equidistant: picks lower

    def test_boundary_low(self):
        strikes = [24800, 24900, 25000]
        assert nearest_strike_index(strikes, 24000) == 0

    def test_boundary_high(self):
        strikes = [24800, 24900, 25000]
        assert nearest_strike_index(strikes, 26000) == 2

    def test_empty_strikes(self):
        assert nearest_strike_index([], 25000) == 0

    def test_none_target(self):
        strikes = [24800, 24900, 25000]
        assert nearest_strike_index(strikes, None) == 0


# ============================================================================
# 3. ATM resolution
# ============================================================================

class TestResolveATM:
    def test_atm_exact(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert resolve_atm(strikes, 25000) == 25000

    def test_atm_between_strikes(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert resolve_atm(strikes, 25030) == 25000

    def test_atm_closer_to_upper(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        assert resolve_atm(strikes, 25070) == 25100

    def test_atm_boundary_low(self):
        strikes = [24800, 24900, 25000]
        assert resolve_atm(strikes, 24000) == 24800

    def test_atm_boundary_high(self):
        strikes = [24800, 24900, 25000]
        assert resolve_atm(strikes, 26000) == 25000

    def test_atm_single_strike(self):
        assert resolve_atm([25000], 25030) == 25000

    def test_atm_empty_chain_raises(self):
        with pytest.raises(ValueError, match="no strikes"):
            resolve_atm([], 25000)

    def test_atm_no_spot_raises(self):
        with pytest.raises(ValueError, match="spot price"):
            resolve_atm([25000], None)


# ============================================================================
# 4. Fixed strike
# ============================================================================

class TestResolveFixedStrike:
    def test_exact_match(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_fixed_strike(strikes, 25000)
        assert strike == 25000
        assert warnings == []

    def test_unlisted_raises_strike_unavailable(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        with pytest.raises(ValueError, match="STRIKE_UNAVAILABLE"):
            resolve_fixed_strike(strikes, 25050)

    def test_none_strike_raises(self):
        with pytest.raises(ValueError, match="numeric value"):
            resolve_fixed_strike([25000], None)

    def test_empty_chain_raises(self):
        with pytest.raises(ValueError, match="no strikes"):
            resolve_fixed_strike([], 25000)


# ============================================================================
# 5. ATM offset steps
# ============================================================================

class TestResolveATMOffsetSteps:
    def test_positive_steps(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset_steps(strikes, 25000, 2)
        assert strike == 25200
        assert warnings == []

    def test_negative_steps(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset_steps(strikes, 25000, -2)
        assert strike == 24800
        assert warnings == []

    def test_zero_steps(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset_steps(strikes, 25000, 0)
        assert strike == 25000

    def test_clamp_high(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset_steps(strikes, 25000, 10)
        assert strike == 25200  # clamped to last
        assert any("exceed the chain" in w for w in warnings)

    def test_clamp_low(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset_steps(strikes, 25000, -10)
        assert strike == 24800  # clamped to first
        assert any("below the chain" in w for w in warnings)

    def test_atm_not_at_center(self):
        # ATM is 25100 (spot = 25070), +2 steps → 25300
        strikes = [24800, 24900, 25000, 25100, 25200, 25300, 25400]
        strike, warnings = resolve_atm_offset_steps(strikes, 25070, 2)
        assert strike == 25300

    def test_empty_chain_raises(self):
        with pytest.raises(ValueError, match="no strikes"):
            resolve_atm_offset_steps([], 25000, 2)

    def test_no_spot_raises(self):
        with pytest.raises(ValueError, match="spot price"):
            resolve_atm_offset_steps([25000], None, 2)

    def test_none_steps_raises(self):
        with pytest.raises(ValueError, match="Steps"):
            resolve_atm_offset_steps([25000], 25000, None)


# ============================================================================
# 6. ATM offset (absolute)
# ============================================================================

class TestResolveATMOffset:
    def test_positive_offset(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset(strikes, 25000, 400)
        assert strike == 25400 if 25400 in strikes else 25200
        # With strikes [24800..25200], ATM=25000, target=25400, nearest=25200
        assert strike == 25200

    def test_negative_offset(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset(strikes, 25000, -400)
        assert strike == 24600 if 24600 in strikes else 24800
        assert strike == 24800

    def test_offset_to_exact_strike(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset(strikes, 25000, 100)
        assert strike == 25100
        assert warnings == []

    def test_offset_normalises_to_nearest(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_atm_offset(strikes, 25000, 50)
        # target = 25050, nearest = 25000
        assert strike == 25000
        assert any("normalised" in w for w in warnings)

    def test_empty_chain_raises(self):
        with pytest.raises(ValueError, match="no strikes"):
            resolve_atm_offset([], 25000, 100)

    def test_no_spot_raises(self):
        with pytest.raises(ValueError, match="spot price"):
            resolve_atm_offset([25000], None, 100)

    def test_none_offset_raises(self):
        with pytest.raises(ValueError, match="Offset"):
            resolve_atm_offset([25000], 25000, None)


# ============================================================================
# 7. Spot offset
# ============================================================================

class TestResolveSpotOffset:
    def test_positive_offset(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_spot_offset(strikes, 25030, 200)
        assert strike == 25200  # 25030+200=25230, nearest=25200

    def test_negative_offset(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_spot_offset(strikes, 25030, -200)
        assert strike == 24800  # 25030-200=24830, nearest=24800

    def test_offset_to_exact_strike(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_spot_offset(strikes, 25030, -30)
        assert strike == 25000  # 25030-30=25000
        assert warnings == []

    def test_normalises_to_nearest(self):
        strikes = [24800, 24900, 25000, 25100, 25200]
        strike, warnings = resolve_spot_offset(strikes, 25030, 50)
        # 25030+50=25080, nearest=25100
        assert strike == 25100
        # 25080 ≠ 25100 → warning
        assert any("normalised" in w for w in warnings)

    def test_empty_chain_raises(self):
        with pytest.raises(ValueError, match="no strikes"):
            resolve_spot_offset([], 25000, 100)

    def test_no_spot_raises(self):
        with pytest.raises(ValueError, match="spot price"):
            resolve_spot_offset([25000], None, 100)

    def test_none_offset_raises(self):
        with pytest.raises(ValueError, match="Offset"):
            resolve_spot_offset([25000], 25000, None)


# ============================================================================
# 8. Delta targeting
# ============================================================================

class TestResolveDeltaTarget:
    def test_ce_delta_030(self):
        """CE delta ≈ 0.30 should find an OTM call."""
        rows = [
            _chain_row(24500, call_delta=0.80),
            _chain_row(24700, call_delta=0.65),
            _chain_row(24900, call_delta=0.45),
            _chain_row(25000, call_delta=0.30),  # ← target
            _chain_row(25100, call_delta=0.18),
            _chain_row(25300, call_delta=0.05),
        ]
        row, delta, warnings = resolve_delta_target(rows, "call", 0.30)
        assert row["strike"] == 25000
        assert delta == 0.30
        assert warnings == []

    def test_pe_delta_neg030(self):
        """PE delta ≈ −0.30 should find an OTM put."""
        rows = [
            _chain_row(24500, put_delta=-0.05),
            _chain_row(24700, put_delta=-0.18),
            _chain_row(24900, put_delta=-0.30),  # ← target
            _chain_row(25000, put_delta=-0.45),
            _chain_row(25100, put_delta=-0.65),
            _chain_row(25300, put_delta=-0.80),
        ]
        row, delta, warnings = resolve_delta_target(rows, "put", -0.30)
        assert row["strike"] == 24900
        assert delta == -0.30
        assert warnings == []

    def test_equal_distance_picks_closest_to_atm(self):
        """When two strikes have equal delta distance, pick the one nearest ATM."""
        rows = [
            _chain_row(24800, call_delta=0.25),  # diff = 0.05
            _chain_row(25000, call_delta=0.35),  # diff = 0.05 (equal)
            _chain_row(25200, call_delta=0.15),
        ]
        # With spot = 25000, ATM = 25000. Both 24800 and 25000 are equally
        # distant from 0.30. The one closest to ATM (25000) should win.
        row, delta, warnings = resolve_delta_target(rows, "call", 0.30, spot=25000)
        assert row["strike"] == 25000

    def test_equal_distance_no_spot_picks_first(self):
        """Without spot, tie is broken by list order (first encountered)."""
        rows = [
            _chain_row(24800, call_delta=0.25),
            _chain_row(25000, call_delta=0.35),
        ]
        row, delta, warnings = resolve_delta_target(rows, "call", 0.30)
        # Both have diff=0.05; first in list wins (24800)
        assert row["strike"] == 24800

    def test_missing_greeks_raises(self):
        """No delta data for any strike → error."""
        rows = [
            _chain_row(24800, call_delta=None),
            _chain_row(25000, call_delta=None),
        ]
        with pytest.raises(ValueError, match="not available"):
            resolve_delta_target(rows, "call", 0.30)

    def test_unreachable_delta_raises(self):
        """Target delta too far from any available → error."""
        rows = [
            _chain_row(24800, call_delta=0.80),
            _chain_row(25000, call_delta=0.75),
            _chain_row(25200, call_delta=0.70),
        ]
        with pytest.raises(ValueError, match="unreachable"):
            resolve_delta_target(rows, "call", 0.30)

    def test_approximate_delta_warns(self):
        """Delta within 0.10–0.20 of target → warning, not error."""
        rows = [
            _chain_row(24800, call_delta=0.55),
            _chain_row(25000, call_delta=0.45),
            _chain_row(25200, call_delta=0.15),
        ]
        # diff = |0.15 - 0.30| = 0.15 → within warning range
        row, delta, warnings = resolve_delta_target(rows, "call", 0.30)
        assert row["strike"] == 25200
        assert delta == 0.15
        assert any("approximate" in w for w in warnings)

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError, match="no rows"):
            resolve_delta_target([], "call", 0.30)

    def test_none_target_raises(self):
        with pytest.raises(ValueError, match="Target delta"):
            resolve_delta_target([_chain_row(25000)], "call", None)

    def test_invalid_option_type_raises(self):
        """Only 'call' and 'put' are accepted.  Invalid values must produce
        INVALID_OPTION_TYPE, not silently treated as 'put'."""
        rows = [_chain_row(25000, call_delta=0.50)]
        with pytest.raises(ValueError, match="INVALID_OPTION_TYPE"):
            resolve_delta_target(rows, "ce", 0.30)
        with pytest.raises(ValueError, match="INVALID_OPTION_TYPE"):
            resolve_delta_target(rows, "CE", 0.30)
        with pytest.raises(ValueError, match="INVALID_OPTION_TYPE"):
            resolve_delta_target(rows, "", 0.30)


# ============================================================================
# 9. Expiry resolution
# ============================================================================

class TestResolveExpiryFixed:
    def test_exact_match(self):
        exp, w = resolve_expiry_fixed(NIFTY_EXPIRIES, "2026-08-27")
        assert exp == "2026-08-27"
        assert w == []

    def test_unlisted_raises_expiry_unavailable(self):
        with pytest.raises(ValueError, match="EXPIRY_UNAVAILABLE"):
            resolve_expiry_fixed(NIFTY_EXPIRIES, "2099-01-01")

    def test_empty_expiries_raises(self):
        with pytest.raises(ValueError, match="No expiries"):
            resolve_expiry_fixed([], "2026-08-27")


class TestResolveExpiryCurrentWeek:
    def test_returns_nearest_future_expiry(self):
        """current_week returns the nearest listed expiry >= today."""
        today = date(2026, 8, 19)  # Wednesday
        exp, w = resolve_expiry_current_week(NIFTY_EXPIRIES, today=today)
        assert exp == "2026-08-20"  # nearest future expiry

    def test_on_expiry_day_returns_that_expiry(self):
        """If today IS a listed expiry date, return it."""
        exp, w = resolve_expiry_current_week(NIFTY_EXPIRIES, today=date(2026, 8, 27))
        assert exp == "2026-08-27"

    def test_after_all_expiries_fallback(self):
        """When today is past all expiries, fallback to nearest."""
        exp, w = resolve_expiry_current_week(NIFTY_EXPIRIES, today=date(2026, 12, 1))
        assert exp == "2026-09-24"  # nearest overall
        assert any("No ideal" in x for x in w)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No expiries"):
            resolve_expiry_current_week([])


class TestResolveExpiryNextWeek:
    def test_returns_second_nearest_future(self):
        """next_week returns the second-nearest listed expiry >= today."""
        today = date(2026, 8, 19)  # Wednesday
        exp, w = resolve_expiry_next_week(NIFTY_EXPIRIES, today=today)
        assert exp == "2026-08-27"  # second-nearest future expiry

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No expiries"):
            resolve_expiry_next_week([])


class TestResolveExpiryMonthly:
    def test_returns_latest_in_month(self):
        exp, w = resolve_expiry_monthly(NIFTY_EXPIRIES)
        d = date.fromisoformat(exp)
        today = date.today()
        assert d.year == today.year
        assert d.month == today.month
        # Should be the latest
        for e in NIFTY_EXPIRIES:
            ed = date.fromisoformat(e)
            if ed.year == today.year and ed.month == today.month:
                assert ed <= d

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No expiries"):
            resolve_expiry_monthly([])


class TestResolveExpiryDTERange:
    def test_within_range(self):
        exp, w = resolve_expiry_dte_range(NIFTY_EXPIRIES, dte_min=5, dte_max=15)
        d = date.fromisoformat(exp)
        dte = (d - date.today()).days
        assert 5 <= dte <= 15

    def test_picks_highest_dte(self):
        exp, w = resolve_expiry_dte_range(NIFTY_EXPIRIES, dte_min=1, dte_max=30)
        d = date.fromisoformat(exp)
        dte = (d - date.today()).days
        # Among qualifying, should pick the one with most time
        for e in NIFTY_EXPIRIES:
            ed = date.fromisoformat(e)
            edte = (ed - date.today()).days
            if 1 <= edte <= 30:
                assert edte <= dte

    def test_deterministic_selection(self):
        """DTE-range selection is deterministic: same inputs always produce
        the same output.  The highest-DTE rule is a simple, repeatable
        heuristic — no randomness, no external dependencies.

        Today = Aug 19, 2026 → DTEs: Sep 3 = 15, Sep 10 = 22, Sep 17 = 29.
        With dte_min=10, dte_max=30, all three qualify; the highest DTE
        (Sep 17) is always selected."""
        expiries = ["2026-09-03", "2026-09-10", "2026-09-17"]
        results = [
            resolve_expiry_dte_range(expiries, dte_min=10, dte_max=30)[0]
            for _ in range(10)
        ]
        assert len(set(results)) == 1, f"Non-deterministic: {results}"
        assert results[0] == "2026-09-17"

    def test_no_match_picks_nearest(self):
        exp, w = resolve_expiry_dte_range(NIFTY_EXPIRIES, dte_min=200, dte_max=300)
        assert exp in NIFTY_EXPIRIES
        assert any("No ideal" in x for x in w)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="No expiries"):
            resolve_expiry_dte_range([], dte_min=5, dte_max=10)

    def test_none_dte_raises(self):
        with pytest.raises(ValueError, match="DTE range"):
            resolve_expiry_dte_range(NIFTY_EXPIRIES, dte_min=None, dte_max=10)


# ============================================================================
# 10. Holiday / non-standard broker-listed expiries
# ============================================================================

class TestNonStandardExpiries:
    """When broker lists expiries on non-standard dates (holidays), the
    resolver must use the broker-provided list, not compute any weekday."""

    def test_holiday_adjusted_expiry(self):
        """If the broker lists a Monday expiry (holiday-adjusted from Tuesday),
        the resolver picks it based purely on the broker list."""
        # 2026-08-17 is a Monday; broker moved Tue expiry to Mon due to holiday
        expiries = ["2026-08-17", "2026-08-27"]
        today = date(2026, 8, 16)  # Sunday
        exp, w = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-17"  # nearest future expiry from broker list

    def test_non_tuesday_expiry(self):
        """Prove the resolver follows broker-listed dates, not weekday assumptions.

        All expiries are on Wednesdays and Fridays — no Tuesday at all.
        The resolver must still pick correctly from the broker list."""
        expiries = ["2026-08-19", "2026-08-21", "2026-08-28"]  # Wed, Fri, Fri
        today = date(2026, 8, 18)  # Tuesday
        exp, w = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-19"  # nearest future (Wednesday)

    def test_friday_only_weekly_expiry(self):
        """If the only listed expiry is a Friday, it should still be selected."""
        expiries = ["2026-08-21", "2026-08-28"]
        today = date(2026, 8, 19)  # Wednesday
        exp, w = resolve_expiry_current_week(expiries, today=today)
        assert exp == "2026-08-21"  # nearest future (Friday)

    def test_next_week_with_holiday_adjusted_list(self):
        """next_week should return the second-nearest future expiry
        when the broker list includes a holiday-adjusted date."""
        # Mon=holiday-adjusted, Tue=regular, next Tue=next week
        expiries = ["2026-08-17", "2026-08-18", "2026-08-25"]
        today = date(2026, 8, 16)  # Sunday
        exp, w = resolve_expiry_next_week(expiries, today=today)
        assert exp == "2026-08-18"  # second-nearest future

    def test_monthly_tuesday_last_of_month(self):
        """NIFTY last-Tuesday monthly: broker lists Tue expiries,
        monthly should pick the latest in the current month."""
        # Aug 2026: Tue 18 (past), Tue 25 (future)
        # Sep 2026: Tue 1, Tue 8, Tue 15, Tue 22, Tue 29
        expiries = [
            "2026-08-18", "2026-08-25",
            "2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29",
        ]
        # In August: monthly picks 2026-08-25
        exp, w = resolve_expiry_monthly(expiries, today=date(2026, 8, 19))
        assert exp == "2026-08-25"
        # In September: monthly picks 2026-09-29 (last Tuesday)
        exp, w = resolve_expiry_monthly(expiries, today=date(2026, 9, 10))
        assert exp == "2026-09-29"

    def test_custom_expiry_list(self):
        """Resolver works with any arbitrary expiry list the broker provides."""
        expiries = ["2026-08-17", "2026-08-24", "2026-08-31"]
        exp, w = resolve_expiry_monthly(expiries)
        d = date.fromisoformat(exp)
        today = date.today()
        assert d.month == today.month


# ============================================================================
# 11. Backward compatibility with fixed-leg templates
# ============================================================================

class TestBackwardCompatibility:
    """Phase 6.7 fixed-leg templates must continue working unchanged."""

    def test_fixed_leg_resolves_correctly(self):
        """A Phase 6.7 template: BUY CE 25000, expiry 2026-08-27."""
        formula = LegFormula(
            action="buy",
            option_type="call",
            quantity=1,
            lot_size=65,
            strike_mode=StrikeMode.FIXED,
            strike=25000.0,
            expiry_mode=ExpiryMode.FIXED,
            expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok
        assert result.leg.resolved_strike == 25000
        assert result.leg.resolved_expiry == "2026-08-27"
        assert result.leg.action == "buy"
        assert result.leg.option_type == "call"
        assert result.leg.quantity == 1
        assert result.leg.lot_size == 65

    def test_to_execution_leg_shape(self):
        """The resolved leg produces exactly the ExecutionLegIn shape."""
        formula = LegFormula(
            action="sell",
            option_type="put",
            quantity=2,
            lot_size=65,
            strike_mode=StrikeMode.FIXED,
            strike=24900.0,
            expiry_mode=ExpiryMode.FIXED,
            expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok
        leg = result.leg.to_execution_leg("NIFTY")
        assert leg == {
            "symbol": "NIFTY",
            "expiration_date": "2026-08-27",
            "strike_price": 24900,
            "option_type": "put",
            "action": "sell",
            "quantity": 2,
            "lot_size": 65,
        }


# ============================================================================
# 12. Full resolve_leg integration tests
# ============================================================================

class TestResolveLegIntegration:
    def test_atm_call(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok
        # ATM for spot=25030 should be 25000
        assert result.leg.resolved_strike == 25000

    def test_atm_offset_steps_call(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM_OFFSET_STEPS, strike_offset_steps=2,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok
        # ATM=25000, +2 steps = 25200
        assert result.leg.resolved_strike == 25200

    def test_atm_offset_put(self):
        formula = LegFormula(
            action="sell", option_type="put", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM_OFFSET, strike_offset=-100,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok
        # ATM=25000, -100=24900
        assert result.leg.resolved_strike == 24900

    def test_spot_offset_call(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.SPOT_OFFSET, strike_offset=200,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok
        # spot=25030, +200=25230, nearest=25200
        assert result.leg.resolved_strike == 25200

    def test_delta_ce(self):
        rows = [
            _chain_row(s, call_delta=max(0.01, min(0.99, 0.5 + (s - NIFTY_SPOT) / 2000)))
            for s in NIFTY_STRIKES
        ]
        chain = {
            "symbol": "NIFTY", "expiry_date": "2026-08-27",
            "underlying_spot_price": NIFTY_SPOT, "chain": rows,
        }
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.DELTA, target_delta=0.30,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok

    def test_delta_pe(self):
        rows = [
            _chain_row(s, put_delta=max(-0.99, min(-0.01, -0.5 + (s - NIFTY_SPOT) / 2000)))
            for s in NIFTY_STRIKES
        ]
        chain = {
            "symbol": "NIFTY", "expiry_date": "2026-08-27",
            "underlying_spot_price": NIFTY_SPOT, "chain": rows,
        }
        formula = LegFormula(
            action="buy", option_type="put", quantity=1, lot_size=65,
            strike_mode=StrikeMode.DELTA, target_delta=-0.30,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert result.ok

    def test_missing_chain_empty(self):
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        result = resolve_leg(formula, {"chain": []})
        assert not result.ok
        assert any("no strikes" in e for e in result.errors)

    def test_fixed_strike_unavailable_blocks(self):
        """When a fixed strike is not listed, the resolver must block with
        STRIKE_UNAVAILABLE — the chain's listed strikes are authoritative."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.FIXED, strike=26000.0,
            expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert not result.ok
        assert any("STRIKE_UNAVAILABLE" in e for e in result.errors)

    def test_missing_expiry_blocks(self):
        """When a fixed expiry is not listed, the resolver must block with
        EXPIRY_UNAVAILABLE — the broker-provided expiry list is authoritative."""
        formula = LegFormula(
            action="buy", option_type="call", quantity=1, lot_size=65,
            strike_mode=StrikeMode.ATM,
            expiry_mode=ExpiryMode.FIXED, expiry="2099-01-01",
        )
        chain = _chain_response(NIFTY_STRIKES, NIFTY_SPOT)
        result = resolve_leg(formula, chain, available_expiries=NIFTY_EXPIRIES)
        assert not result.ok
        assert any("EXPIRY_UNAVAILABLE" in e for e in result.errors)


# ============================================================================
# 13. Edge cases
# ============================================================================

class TestEdgeCases:
    def test_empty_chain_no_strikes(self):
        result = resolve_leg(
            LegFormula(
                action="buy", option_type="call", quantity=1, lot_size=65,
                strike_mode=StrikeMode.ATM,
                expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
            ),
            {"chain": [], "underlying_spot_price": 25000},
        )
        assert not result.ok

    def test_spot_none_with_atm(self):
        result = resolve_leg(
            LegFormula(
                action="buy", option_type="call", quantity=1, lot_size=65,
                strike_mode=StrikeMode.ATM,
                expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
            ),
            {"chain": [_chain_row(25000)]},
        )
        assert not result.ok
        assert any("spot price" in e for e in result.errors)

    def test_single_strike_chain(self):
        result = resolve_leg(
            LegFormula(
                action="buy", option_type="call", quantity=1, lot_size=65,
                strike_mode=StrikeMode.ATM,
                expiry_mode=ExpiryMode.FIXED, expiry="2026-08-27",
            ),
            {"chain": [_chain_row(25000)], "underlying_spot_price": 25000},
            available_expiries=NIFTY_EXPIRIES,
        )
        assert result.ok
        assert result.leg.resolved_strike == 25000
