"""Day 18 — Scenario & Time Analysis + Portfolio Sensitivity tests (RED-phase
contract).

Proves the deterministic backend scenario engine on the Day-14 boundary:

    Explicit scenario coordinates (spot, T, sigma) over an OptionLeg
        → scenario_value (Day-16 pricing engine, reused)
        → model Greeks (Day-15 Greeks engine, reused) exposure-scaled
        → QuantResult (quality + provenance + versions preserved)
    Price × Time × IV grids and portfolio aggregation are deterministic.

Rules locked by these tests
---------------------------
1. The scenario module REUSES the Day-15/16 authoritative pure functions —
   no duplicated Black-Scholes/Greek math (scenario_value must equal the
   Day-16 engine at identical inputs).
2. Deterministic: spot, time-to-expiry and IV are explicit per scenario;
   the engine NEVER reads the wall clock; scenario T < 0 is invalid; T = 0
   evaluates the Day-16 intrinsic convention (call max(S−K,0), put
   max(K−S,0)) and the Day-15 step convention for Greeks.
3. P/L semantics: per-unit model value; position P/L =
   direction_sign × (scenario_value − entry_price) × quantity, with explicit
   long/short direction (±1) and quantity in contracts (zero valid). Entry
   price is explicit; P/L is unavailable without it. Model values are never
   presented as broker/execution truth.
4. No fabrication: missing provenance / INSUFFICIENT quality ⇒ UNAVAILABLE
   with the Day-14 structured reasons; missing IV ⇒ UNAVAILABLE; invalid
   inputs ⇒ INVALID_INPUT; no NaN/Infinity, no silent coercion.
5. Grid ordering is canonical and deterministic: lexicographic (spot, time,
   iv) with iv varying fastest; count = n_spots × n_times × n_ivs.
6. Portfolio aggregation is pure summation over per-leg results (P/L,
   delta/gamma/vega/theta); model sensitivities never claim broker status;
   quality is consumed (never recomputed — AST enforced).
7. Security: no broker credentials/payloads, no network/DB/wall clock in the
   module (Day-14 AST guards auto-extend; module-level checks also here).

Golden P/L and Greek-exposure expectations are independent arithmetic on the
already-externally-validated Day-15/16 golden prices/greeks (ATM call 10.4506,
put 5.5735, delta 0.6368, …) — never derived by calling the production
scenario functions.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import (
    DataMode,
    Provenance,
    QualityState,
    Side,
)
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    QuantResult,
)
from app.quant.greeks import black_scholes_merton_greeks
from app.quant.pricing import black_scholes_merton_price
from app.quant.scenarios import (
    CALCULATION_ID,
    MODEL_NAME,
    MODEL_VERSION,
    CALCULATION_VERSION,
    GREEKS_MODEL_FAMILY,
    OptionLeg,
    PortfolioScenarioResult,
    PositionDirection,
    ScenarioGrid,
    ScenarioPoint,
    evaluate_leg,
    evaluate_leg_grid,
    evaluate_portfolio,
    scenario_value,
)

_EXPIRY = "2028-09-03"
_REF = datetime(2028, 8, 3, 10, 0, 0, tzinfo=timezone.utc)

# Independent golden constants from Days 15/16 (externally validated):
ATM_CALL_1Y = 10.450583572186   # S=K=100, T=1, sigma=0.2, r=0.05, q=0
ATM_PUT_1Y = 5.573526022257
CALL_DELTA = 0.636830651176
CALL_GAMMA = 0.018762017346
CALL_VEGA = 37.524034691694
CALL_THETA = -6.414027546438
PUT_DELTA = -0.363169348824
PUT_THETA = -1.657880423935


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prov() -> Provenance:
    return Provenance(
        source="UPSTOX",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=_REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _ctx(*, risk_free: float = 0.05, dividend: float | None = None) -> CalculationContext:
    return CalculationContext(
        reference_timestamp=_REF,
        risk_free_rate=risk_free,
        dividend_yield=dividend,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )


_UNSET = object()


def _leg(
    *,
    side: Side = Side.CALL,
    strike: float = 100.0,
    quantity: float = 1.0,
    direction: PositionDirection = PositionDirection.LONG,
    entry_price: float | None = 9.0,
    implied_volatility: float | None = 0.2,
    quality: QualityState | None = QualityState.EXCELLENT,
    prov: object = _UNSET,
) -> OptionLeg:
    return OptionLeg(
        option_type=side,
        strike=strike,
        expiry=_EXPIRY,
        quantity=quantity,
        direction=direction,
        entry_price=entry_price,
        implied_volatility=implied_volatility,
        quality=quality,
        provenance=prov if prov is not _UNSET else _prov(),
    )


def _eval(leg: OptionLeg, ctx: CalculationContext | None = None, **scenario) -> QuantResult:
    return evaluate_leg(leg, ctx or _ctx(), **scenario)


# ---------------------------------------------------------------------------
# 1. Scenario contract / leg validation
# ---------------------------------------------------------------------------


class TestScenarioContract:
    def test_valid_leg_construction(self):
        leg = _leg()
        assert leg.option_type is Side.CALL
        assert leg.strike == 100.0
        assert leg.direction is PositionDirection.LONG
        assert PositionDirection.LONG.sign == 1
        assert PositionDirection.SHORT.sign == -1

    def test_invalid_strike_rejected(self):
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=0.0, expiry=_EXPIRY)
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=-5.0, expiry=_EXPIRY)
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=float("nan"), expiry=_EXPIRY)

    def test_invalid_option_type_rejected(self):
        with pytest.raises(ValueError):
            OptionLeg(option_type="CALL", strike=100.0, expiry=_EXPIRY)

    def test_invalid_expiry_rejected(self):
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=100.0, expiry="not-a-date")

    def test_invalid_quantity_rejected(self):
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=100.0, expiry=_EXPIRY, quantity=-2.0)
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=100.0, expiry=_EXPIRY, quantity=float("inf"))

    def test_zero_quantity_permitted(self):
        leg = OptionLeg(option_type=Side.CALL, strike=100.0, expiry=_EXPIRY, quantity=0.0)
        assert leg.quantity == 0.0

    def test_invalid_iv_on_leg_rejected(self):
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=100.0, expiry=_EXPIRY,
                      implied_volatility=-0.1)
        with pytest.raises(ValueError):
            OptionLeg(option_type=Side.CALL, strike=100.0, expiry=_EXPIRY,
                      implied_volatility=float("nan"))


# ---------------------------------------------------------------------------
# 2. Pricing integration — scenario_value reuses the Day-16 engine
# ---------------------------------------------------------------------------


class TestPricingIntegration:
    @pytest.mark.parametrize("side,strike", [(Side.CALL, 100.0), (Side.PUT, 100.0),
                                             (Side.CALL, 110.0), (Side.PUT, 90.0),
                                             (Side.CALL, 90.0), (Side.PUT, 110.0)])
    def test_scenario_value_equals_day16_price_engine(self, side, strike):
        spot, t, sig, r, q = 100.0, 1.0, 0.2, 0.05, 0.0
        value = scenario_value(option_type=side, spot=spot, strike=strike,
                               time_to_expiry=t, implied_volatility=sig,
                               risk_free_rate=r, dividend_yield=q)
        expected = black_scholes_merton_price(
            option_type=side, spot=spot, strike=strike, time_to_expiry=t,
            volatility=sig, risk_free_rate=r, dividend_yield=q,
        )
        assert value == pytest.approx(expected, rel=1e-12)

    def test_atm_golden_call_and_put(self):
        assert scenario_value(option_type=Side.CALL, spot=100.0, strike=100.0,
                              time_to_expiry=1.0, implied_volatility=0.2,
                              risk_free_rate=0.05, dividend_yield=0.0) == pytest.approx(
            ATM_CALL_1Y, rel=1e-9)
        assert scenario_value(option_type=Side.PUT, spot=100.0, strike=100.0,
                              time_to_expiry=1.0, implied_volatility=0.2,
                              risk_free_rate=0.05, dividend_yield=0.0) == pytest.approx(
            ATM_PUT_1Y, rel=1e-9)

    def test_t0_is_intrinsic_value(self):
        assert scenario_value(option_type=Side.CALL, spot=100.0, strike=90.0,
                              time_to_expiry=0.0, implied_volatility=0.2,
                              risk_free_rate=0.05, dividend_yield=0.0) == pytest.approx(10.0)
        assert scenario_value(option_type=Side.CALL, spot=90.0, strike=100.0,
                              time_to_expiry=0.0, implied_volatility=0.2,
                              risk_free_rate=0.05, dividend_yield=0.0) == pytest.approx(0.0)
        assert scenario_value(option_type=Side.PUT, spot=90.0, strike=100.0,
                              time_to_expiry=0.0, implied_volatility=0.2,
                              risk_free_rate=0.05, dividend_yield=0.0) == pytest.approx(10.0)
        assert scenario_value(option_type=Side.PUT, spot=110.0, strike=100.0,
                              time_to_expiry=0.0, implied_volatility=0.2,
                              risk_free_rate=0.05, dividend_yield=0.0) == pytest.approx(0.0)

    def test_deep_itm_and_otm_finite(self):
        for side, spot in [(Side.CALL, 1e6), (Side.CALL, 1e-6), (Side.PUT, 1e6), (Side.PUT, 1e-6)]:
            value = scenario_value(option_type=side, spot=spot, strike=100.0,
                                   time_to_expiry=1.0, implied_volatility=0.3,
                                   risk_free_rate=0.05, dividend_yield=0.0)
            assert math.isfinite(value)

    def test_invalid_pure_inputs_raise(self):
        with pytest.raises(ValueError):
            scenario_value(option_type=Side.CALL, spot=0.0, strike=100.0,
                           time_to_expiry=1.0, implied_volatility=0.2,
                           risk_free_rate=0.05, dividend_yield=0.0)
        with pytest.raises(ValueError):
            scenario_value(option_type=Side.CALL, spot=100.0, strike=100.0,
                           time_to_expiry=-0.1, implied_volatility=0.2,
                           risk_free_rate=0.05, dividend_yield=0.0)
        with pytest.raises(ValueError):
            scenario_value(option_type=Side.CALL, spot=100.0, strike=100.0,
                           time_to_expiry=1.0, implied_volatility=-0.01,
                           risk_free_rate=0.05, dividend_yield=0.0)
        with pytest.raises(ValueError):
            scenario_value(option_type=Side.CALL, spot=float("inf"), strike=100.0,
                           time_to_expiry=1.0, implied_volatility=0.2,
                           risk_free_rate=0.05, dividend_yield=0.0)


# ---------------------------------------------------------------------------
# 3. evaluate_leg — single scenario evaluation
# ---------------------------------------------------------------------------


class TestEvaluateLeg:
    def test_atm_long_call_scenario_matches_golden(self):
        result = _eval(_leg(entry_price=9.0), spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["scenario_value"] == pytest.approx(ATM_CALL_1Y, rel=1e-9)
        assert result.values["delta"] == pytest.approx(CALL_DELTA, rel=1e-9)
        assert result.values["gamma"] == pytest.approx(CALL_GAMMA, rel=1e-9)
        assert result.values["vega"] == pytest.approx(CALL_VEGA, rel=1e-9)
        assert result.values["theta"] == pytest.approx(CALL_THETA, rel=1e-9)
        assert result.values["pnl"] == pytest.approx(1.450583572186, rel=1e-9)

    def test_values_include_scenario_coordinates(self):
        result = _eval(_leg(), spot=105.0, time_to_expiry=0.5, implied_volatility=0.25)
        assert result.values["spot"] == pytest.approx(105.0)
        assert result.values["time_to_expiry"] == pytest.approx(0.5)
        assert result.values["implied_volatility"] == pytest.approx(0.25)

    def test_default_iv_comes_from_leg_only(self):
        result = _eval(_leg(implied_volatility=0.18), spot=100.0, time_to_expiry=1.0)
        assert result.values["implied_volatility"] == pytest.approx(0.18)

    def test_no_iv_anywhere_is_unavailable(self):
        leg = _leg(implied_volatility=None)
        result = _eval(leg, spot=100.0, time_to_expiry=1.0, implied_volatility=None)
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)
        assert result.values is None

    def test_invalid_scenario_spot_is_invalid_input(self):
        result = _eval(_leg(), spot=0.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.INVALID_INPUT
        assert result.values is None

    def test_negative_scenario_time_is_invalid_input(self):
        result = _eval(_leg(), spot=100.0, time_to_expiry=-0.1)
        assert result.status is CalculationStatus.INVALID_INPUT
        assert result.values is None

    def test_negative_scenario_iv_is_invalid_input(self):
        result = _eval(_leg(), spot=100.0, time_to_expiry=1.0, implied_volatility=-0.1)
        assert result.status is CalculationStatus.INVALID_INPUT
        assert result.values is None

    def test_t0_evaluates_through_intrinsic_convention(self):
        result = _eval(_leg(side=Side.CALL, strike=90.0), spot=100.0, time_to_expiry=0.0)
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["scenario_value"] == pytest.approx(10.0, rel=1e-12)

    def test_entry_price_absent_pnl_omitted(self):
        result = _eval(_leg(entry_price=None), spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.SUCCESS
        assert "pnl" not in result.values
        assert result.values["scenario_value"] == pytest.approx(ATM_CALL_1Y, rel=1e-9)

    def test_short_position_flips_pnl(self):
        result = _eval(_leg(direction=PositionDirection.SHORT, entry_price=11.0),
                       spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.SUCCESS
        # short is in profit: value fell from 11.0 entry to 10.4506
        assert result.values["pnl"] == pytest.approx(+0.549416427814, rel=1e-9)

    def test_quantity_scales_pnl_and_exposure(self):
        result = _eval(_leg(quantity=4.0, entry_price=9.0), spot=100.0, time_to_expiry=1.0)
        assert result.values["pnl"] == pytest.approx(5.802334288744, rel=1e-9)
        assert result.values["delta"] == pytest.approx(4 * CALL_DELTA, rel=1e-9)
        assert result.values["vega"] == pytest.approx(4 * CALL_VEGA, rel=1e-9)

    def test_zero_quantity_yields_zero_pnl_and_exposure(self):
        result = _eval(_leg(quantity=0.0, entry_price=9.0), spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["pnl"] == 0.0
        assert result.values["delta"] == 0.0
        assert result.values["gamma"] == 0.0
        assert result.values["vega"] == 0.0

    def test_long_put_golden(self):
        leg = _leg(side=Side.PUT, entry_price=6.0)
        result = _eval(leg, spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["scenario_value"] == pytest.approx(ATM_PUT_1Y, rel=1e-9)
        assert result.values["delta"] == pytest.approx(PUT_DELTA, rel=1e-9)
        # qty-1 arithmetic on the golden put: 5.573526022257 - 6.0
        assert result.values["pnl"] == pytest.approx(-0.426473977743, rel=1e-9)


# ---------------------------------------------------------------------------
# 4. Price / time / IV axes
# ---------------------------------------------------------------------------


class TestAxes:
    def test_multiple_price_scenarios(self):
        leg = _leg()
        values = [
            _eval(leg, spot=s, time_to_expiry=1.0).values["scenario_value"]
            for s in (90.0, 100.0, 110.0)
        ]
        # call value monotone increasing in spot
        assert values[0] < values[1] < values[2]
        assert values[1] == pytest.approx(ATM_CALL_1Y, rel=1e-9)

    def test_time_decay_reduces_call_value(self):
        leg = _leg()
        values = [
            _eval(leg, spot=100.0, time_to_expiry=t).values["scenario_value"]
            for t in (1.0, 0.25, 0.01)
        ]
        assert values[0] > values[1] > values[2]

    def test_explicit_expiry_t0(self):
        result = _eval(_leg(), spot=100.0, time_to_expiry=0.0)
        assert result.status is CalculationStatus.SUCCESS
        # ATM at expiry: intrinsic 0 for call at the money
        assert result.values["scenario_value"] == pytest.approx(0.0, abs=1e-12)

    def test_iv_axis_value_monotone_in_volatility(self):
        leg = _leg()
        values = [
            _eval(leg, spot=100.0, time_to_expiry=1.0, implied_volatility=s).values[
                "scenario_value"
            ]
            for s in (0.1, 0.2, 0.3)
        ]
        assert values[0] < values[1] < values[2]
        assert values[1] == pytest.approx(ATM_CALL_1Y, rel=1e-9)

    def test_iv_shock_definition_is_explicit_absolute_values(self):
        # IV - shock / IV / IV + shock expressed as explicit decimals — the
        # engine never derives IV internally.
        base = 0.2
        for sig in (base - 0.02, base, base + 0.02):
            result = _eval(_leg(), spot=100.0, time_to_expiry=1.0, implied_volatility=sig)
            assert result.values["implied_volatility"] == pytest.approx(sig)


# ---------------------------------------------------------------------------
# 5. Scenario grid
# ---------------------------------------------------------------------------


class TestScenarioGrid:
    def test_grid_length_is_cartesian_product(self):
        grid = ScenarioGrid(spots=(90.0, 100.0, 110.0), times=(1.0, 0.5), ivs=(0.1, 0.2))
        assert len(grid.points()) == 3 * 2 * 2

    def test_grid_canonical_ordering(self):
        grid = ScenarioGrid(spots=(90.0, 100.0), times=(1.0, 0.5), ivs=(0.1, 0.2))
        order = [(p.spot, p.time_to_expiry, p.implied_volatility) for p in grid.points()]
        assert order == [
            (90.0, 1.0, 0.1), (90.0, 1.0, 0.2),   # iv varies fastest
            (90.0, 0.5, 0.1), (90.0, 0.5, 0.2),
            (100.0, 1.0, 0.1), (100.0, 1.0, 0.2),
            (100.0, 0.5, 0.1), (100.0, 0.5, 0.2),
        ]

    def test_grid_evaluation_count_and_consistency(self):
        leg = _leg(entry_price=9.0)
        grid = ScenarioGrid(spots=(90.0, 100.0), times=(1.0, 0.5), ivs=(0.1, 0.2))
        results = evaluate_leg_grid(leg, _ctx(), grid)
        assert len(results) == 2 * 2 * 2
        # the ATM/T=1/iv=0.2 cell matches the direct single evaluation
        for point, result in results:
            if (point.spot, point.time_to_expiry, point.implied_volatility) == (100.0, 1.0, 0.2):
                assert result.values["scenario_value"] == pytest.approx(ATM_CALL_1Y, rel=1e-9)
                assert result.values["pnl"] == pytest.approx(1.450583572186, rel=1e-9)

    def test_repeated_grid_execution_identical(self):
        leg = _leg()
        grid = ScenarioGrid(spots=(95.0, 105.0), times=(1.0, 0.5), ivs=(0.15, 0.25))
        a = evaluate_leg_grid(leg, _ctx(), grid)
        b = evaluate_leg_grid(leg, _ctx(), grid)
        assert a == b


# ---------------------------------------------------------------------------
# 6. P/L golden arithmetic
# ---------------------------------------------------------------------------


class TestPnLGolden:
    def test_long_call(self):
        leg = _leg(direction=PositionDirection.LONG, entry_price=9.0)
        result = _eval(leg, spot=100.0, time_to_expiry=1.0)
        assert result.values["pnl"] == pytest.approx(1.450583572186, rel=1e-9)

    def test_short_call_three_lots(self):
        leg = _leg(direction=PositionDirection.SHORT, quantity=3.0, entry_price=11.0)
        result = _eval(leg, spot=100.0, time_to_expiry=1.0)
        # -3 x (10.450583572186 - 11.0) — short profits as value fell below entry
        assert result.values["pnl"] == pytest.approx(+1.648249283442, rel=1e-9)

    def test_long_put_two_lots(self):
        leg = _leg(side=Side.PUT, direction=PositionDirection.LONG, quantity=2.0,
                   entry_price=6.0)
        result = _eval(leg, spot=100.0, time_to_expiry=1.0)
        assert result.values["pnl"] == pytest.approx(-0.852947955486, rel=1e-9)

    def test_pnl_semantics_reference_is_entry_not_market(self):
        # P/L is relative to the explicit entry price — never a broker LTP.
        result = _eval(_leg(entry_price=9.0), spot=100.0, time_to_expiry=1.0)
        assert result.values["pnl"] == pytest.approx(ATM_CALL_1Y - 9.0, rel=1e-9)


# ---------------------------------------------------------------------------
# 7. Portfolio sensitivity foundation
# ---------------------------------------------------------------------------


class TestPortfolio:
    def _two_leg_portfolio(self):
        return [
            _leg(direction=PositionDirection.LONG, quantity=1.0, entry_price=9.0),
            _leg(direction=PositionDirection.SHORT, quantity=3.0, entry_price=11.0),
        ]

    def test_aggregate_pnl_equals_sum_of_legs(self):
        legs = self._two_leg_portfolio()
        result = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        # +1.450583572186 (long qty-1) + 1.648249283442 (short qty-3 profit)
        assert result.total_pnl == pytest.approx(3.098832855628, rel=1e-9)

    def test_aggregate_greeks_equal_sum_of_legs(self):
        legs = self._two_leg_portfolio()
        result = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        assert result.delta == pytest.approx(-1.273661302352, rel=1e-9)
        assert result.gamma == pytest.approx(-0.037524034692, rel=1e-9)
        assert result.vega == pytest.approx(-75.048069383388, rel=1e-9)
        assert result.theta == pytest.approx(12.828055092876, rel=1e-9)

    def test_portfolio_sums_individual_quant_results(self):
        legs = self._two_leg_portfolio()
        total = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        per_leg = [evaluate_leg(l, _ctx(), spot=100.0, time_to_expiry=1.0) for l in legs]
        assert total.total_pnl == pytest.approx(
            sum(r.values["pnl"] for r in per_leg), rel=1e-12)
        assert total.delta == pytest.approx(
            sum(r.values["delta"] for r in per_leg), rel=1e-12)
        assert total.vega == pytest.approx(
            sum(r.values["vega"] for r in per_leg), rel=1e-12)

    def test_mixed_call_put_portfolio(self):
        legs = [
            _leg(side=Side.CALL, direction=PositionDirection.LONG, quantity=1.0,
                 entry_price=9.0),
            _leg(side=Side.PUT, direction=PositionDirection.LONG, quantity=2.0,
                 entry_price=6.0),
        ]
        result = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        # 1.450583572186 + 2 x (5.573526022257 - 6.0)
        assert result.total_pnl == pytest.approx(0.597635616700, rel=1e-9)

    def test_per_leg_results_exposed(self):
        legs = self._two_leg_portfolio()
        result = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        assert len(result.leg_results) == 2
        assert all(r.status is CalculationStatus.SUCCESS for r in result.leg_results)

    def test_not_partial_when_all_legs_price(self):
        result = evaluate_portfolio(self._two_leg_portfolio(), _ctx(),
                                    spot=100.0, time_to_expiry=1.0)
        assert result.partial is False
        assert result.unavailable_reasons == ()

    def test_partial_portfolio_flags_unavailable_legs(self):
        legs = self._two_leg_portfolio()
        legs.append(
            OptionLeg(option_type=Side.CALL, strike=100.0, expiry=_EXPIRY,
                      quantity=1.0, quality=QualityState.INSUFFICIENT,
                      provenance=_prov())
        )
        result = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        assert result.partial is True
        assert any(
            r.code is CalculationIssueCode.INSUFFICIENT_QUALITY
            for r in result.unavailable_reasons
        )
        # totals cover the two priced legs only
        assert result.total_pnl == pytest.approx(3.098832855628, rel=1e-9)

    def test_no_entry_price_anywhere_totals_pnl_none(self):
        legs = [
            _leg(entry_price=None),
            _leg(side=Side.PUT, entry_price=None),
        ]
        result = evaluate_portfolio(legs, _ctx(), spot=100.0, time_to_expiry=1.0)
        assert result.total_pnl is None
        # Greek exposure still aggregates (model sensitivities need no entry)
        assert result.delta == pytest.approx(CALL_DELTA + PUT_DELTA, rel=1e-9)


# ---------------------------------------------------------------------------
# 8. Quality / provenance propagation
# ---------------------------------------------------------------------------


class TestQualityProvenance:
    @pytest.mark.parametrize("q", [QualityState.EXCELLENT, QualityState.GOOD, QualityState.DEGRADED])
    def test_quality_permitted_and_preserved(self, q):
        result = _eval(_leg(quality=q), spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.SUCCESS
        assert result.input_quality is q
        assert result.provenance == _leg(quality=q).provenance
        assert result.reference_timestamp == _REF
        assert result.calculation_id == CALCULATION_ID
        assert result.model_version == MODEL_VERSION
        assert result.calculation_version == CALCULATION_VERSION
        assert result.contract_version == "1.0.0"

    def test_insufficient_quality_unavailable(self):
        result = _eval(_leg(quality=QualityState.INSUFFICIENT), spot=100.0,
                       time_to_expiry=1.0)
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.INSUFFICIENT_QUALITY for i in result.issues)
        assert result.values is None

    def test_missing_provenance_unavailable(self):
        result = _eval(_leg(prov=None), spot=100.0, time_to_expiry=1.0)
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_PROVENANCE for i in result.issues)

    def test_module_never_recomputes_quality(self):
        import ast as _ast
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "app" / "quant" / "scenarios.py"
        text = path.read_text(encoding="utf-8")
        tree = _ast.parse(text)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ImportFrom):
                assert not (node.module or "").startswith("app.market_data.quality")
        assert "MarketDataQualityEngine" not in text


# ---------------------------------------------------------------------------
# 9. Determinism & numerical safety
# ---------------------------------------------------------------------------


class TestDeterminismAndNumericalSafety:
    def test_repeated_evaluation_identical(self):
        leg = _leg()
        ctx = _ctx()
        a = evaluate_leg(leg, ctx, spot=103.5, time_to_expiry=0.7, implied_volatility=0.22)
        b = evaluate_leg(leg, ctx, spot=103.5, time_to_expiry=0.7, implied_volatility=0.22)
        assert a == b

    def test_all_outputs_finite_for_valid_cases(self):
        for side in (Side.CALL, Side.PUT):
            for spot in (0.5, 100.0, 25000.0):
                for t in (0.0, 0.01, 1.0):
                    result = _eval(_leg(side=side), spot=spot, time_to_expiry=t,
                                   implied_volatility=0.25)
                    assert result.status is CalculationStatus.SUCCESS
                    for v in result.values.values():
                        assert math.isfinite(v)

    def test_non_finite_scenario_inputs_rejected(self):
        assert _eval(_leg(), spot=float("nan"), time_to_expiry=1.0).status is CalculationStatus.INVALID_INPUT
        assert _eval(_leg(), spot=float("inf"), time_to_expiry=1.0).status is CalculationStatus.INVALID_INPUT
        assert _eval(_leg(), spot=100.0, time_to_expiry=float("nan")).status is CalculationStatus.INVALID_INPUT
        assert _eval(_leg(), spot=100.0, time_to_expiry=1.0,
                     implied_volatility=float("nan")).status is CalculationStatus.INVALID_INPUT


# ---------------------------------------------------------------------------
# 10. Security & broker neutrality (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    def test_module_has_no_clock_or_io_imports(self):
        import ast as _ast
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "app" / "quant" / "scenarios.py"
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "fastapi"}
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today"}
            if isinstance(node, _ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, _ast.ImportFrom):
                assert not (node.module or "").startswith("app.brokers")
                assert not (node.module or "").startswith("app.services")
                assert not (node.module or "").startswith("app.market_data.quality")

    def test_results_never_leak_credentials_or_broker_payloads(self):
        result = _eval(_leg(), spot=100.0, time_to_expiry=1.0)
        assert "sk_live" not in str(result)
        assert "access_token" not in str(result)
        assert "authorization" not in str(result)

    def test_model_identity_explicit(self):
        assert MODEL_NAME == "SCENARIO_ANALYSIS"
        assert GREEKS_MODEL_FAMILY == "BLACK_SCHOLES_MERTON_EUROPEAN"
