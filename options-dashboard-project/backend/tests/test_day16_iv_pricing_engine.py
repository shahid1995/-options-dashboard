"""Day 16 — Deterministic Pricing + Implied Volatility engine tests (RED-phase
contract).

Proves the second and third real quantitative engines on the Day-14 boundary:

    Canonical option inputs (OptionMarketData + CalculationContext)
        → QuantitativeEngineBoundary (provenance/quality guards)
        → BlackScholesMertonPricingEngine        (app/quant/pricing)
            values = {"price": ...}
        → BlackScholesMertonImpliedVolatilityEngine (app/quant/iv)
            values = {"implied_volatility": ...}  (decimal fraction)
        → QuantResult (values + quality + provenance + versions)

Rules locked by these tests
---------------------------
1. European Black-Scholes-Merton with continuous dividend yield q — the SAME
   convention family as the Day-15 Greeks engine (shared model family name
   ``BLACK_SCHOLES_MERTON_EUROPEAN``).  Price is per-unit.
2. ``T == 0`` pricing returns intrinsic value (never a normal-distribution
   evaluation at T = 0); ``sigma == 0`` uses the deterministic forward-value
   convention (the exact σ→0 limit of the model).
3. The IV solver is a deterministic bounded (Brent) root solve on
   ``price(σ) − market`` over ``[0.0, 10.0]`` with explicit documented
   tolerances and a structured failure taxonomy mapped onto the boundary's
   issue codes: EXPIRED, BELOW_LOWER_BOUND, ABOVE_THEORETICAL_MAX,
   NO_BRACKET, CONVERGENCE_FAILED.
4. IV is returned as a decimal volatility fraction (0.1824 = 18.24%), never a
   percentage-point number.
5. Deterministic + broker-neutral: same inputs + context ⇒ identical results;
   no hidden wall clock / DB / broker / random state (AST rules from Day 14
   auto-extend over the new modules; module-level AST checks also live here).
6. No fabrication: missing required inputs ⇒ UNAVAILABLE; invalid inputs ⇒
   INVALID_INPUT; market price outside model bounds ⇒ structured taxonomy;
   never NaN/Infinity; never a guessed value.
7. Quality is propagated (Day-12 state preserved, never recomputed);
   provenance is preserved; model/calculation versions are explicit; model
   IV/prices never overwrite Day-9 broker observations.

Golden price expectations were computed by an independent closed-form
evaluation of the BS-Merton formulas and cross-checked against the verified
Phase-7.19B implementation (agreement < 1e-12 on every fixture).  The ATM
1-year call (S=K=100, r=5%, σ=20%) matches the classic textbook reference
price ≈ 10.4506.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.market_data.contracts import (
    DataMode,
    GreeksObservation,
    NormalizedInstrument,
    Provenance,
    QualityState,
    Side,
)
from app.quant.boundary import QuantitativeEngineBoundary
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    OptionMarketData,
    QuantResult,
)
from app.quant.greeks import BLACK_SCHOLES_MERTON_EUROPEAN, black_scholes_merton_greeks
from app.quant.iv import (
    CALCULATION_ID as IV_CALCULATION_ID,
    CALCULATION_VERSION as IV_CALCULATION_VERSION,
    MODEL_VERSION as IV_MODEL_VERSION,
    BlackScholesMertonImpliedVolatilityEngine,
    IvSolverOutcome,
    implied_volatility_solve,
)
from app.quant.pricing import (
    CALCULATION_ID as PRICING_CALCULATION_ID,
    CALCULATION_VERSION as PRICING_CALCULATION_VERSION,
    MODEL_VERSION as PRICING_MODEL_VERSION,
    BlackScholesMertonPricingEngine,
    black_scholes_merton_price,
)

_SECONDS_PER_YEAR_ACT_365 = 365.0 * 86400.0
_EXPIRY = "2028-09-03"
_EXPIRY_MIDNIGHT = datetime(2028, 9, 3, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Golden price fixtures (independently computed closed-form values, 12 dp;
# cross-checked against the verified Phase-7.19B implementation and the
# textbook ATM anchor call ≈ 10.4506).
# ---------------------------------------------------------------------------

GOLDEN_PRICES = [
    # name, side, spot, strike, T, sigma, r, q, expected price
    ("ATM_CALL", Side.CALL, 100, 100, 1.0, 0.2, 0.05, 0.0, 10.450583572186),
    ("ATM_PUT", Side.PUT, 100, 100, 1.0, 0.2, 0.05, 0.0, 5.573526022257),
    ("ITM_CALL", Side.CALL, 110, 100, 1.0, 0.2, 0.05, 0.0, 17.662953740590),
    ("ITM_PUT", Side.PUT, 90, 100, 1.0, 0.2, 0.05, 0.0, 10.214164528889),
    ("OTM_CALL", Side.CALL, 90, 100, 1.0, 0.2, 0.05, 0.0, 5.091222078818),
    ("OTM_PUT", Side.PUT, 110, 100, 1.0, 0.2, 0.05, 0.0, 2.785896190662),
    ("SHORT_7D_CALL", Side.CALL, 100, 100, 7 / 365.0, 0.2, 0.05, 0.0, 1.152969233458),
    ("SHORT_7D_PUT", Side.PUT, 100, 100, 7 / 365.0, 0.2, 0.05, 0.0, 1.057124782662),
    ("LONG_2Y_CALL", Side.CALL, 100, 100, 2.0, 0.2, 0.05, 0.0, 16.126779724979),
    ("DIVIDEND_CALL", Side.CALL, 100, 100, 1.0, 0.2, 0.05, 0.02, 9.227005508154),
    ("DIVIDEND_PUT", Side.PUT, 100, 100, 1.0, 0.2, 0.05, 0.02, 6.330080627550),
    ("HIGH_VOL_CALL", Side.CALL, 100, 100, 1.0, 0.6, 0.05, 0.0, 25.523205665610),
    ("LOW_VOL_CALL", Side.CALL, 100, 100, 1.0, 0.05, 0.05, 0.0, 5.283268987650),
    ("LOW_VOL_PUT", Side.PUT, 100, 100, 1.0, 0.05, 0.05, 0.0, 0.406211437721),
    ("ZERO_RATE_CALL", Side.CALL, 100, 100, 0.25, 0.6, 0.0, 0.0, 11.923538474048),
    ("ZERO_RATE_PUT", Side.PUT, 100, 100, 0.25, 0.6, 0.0, 0.0, 11.923538474048),
    ("RATE_Q_CALL", Side.CALL, 120, 100, 0.5, 0.3, 0.07, 0.03, 23.706186320305),
    ("RATE_Q_PUT", Side.PUT, 120, 100, 0.5, 0.3, 0.07, 0.03, 2.053295193695),
    ("SPOT80_CALL", Side.CALL, 80, 100, 0.5, 0.3, 0.07, 0.03, 1.664380957116),
    ("SPOT80_PUT", Side.PUT, 80, 100, 0.5, 0.3, 0.07, 0.03, 19.415967414628),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _option_instrument(*, side: Side, strike: float) -> NormalizedInstrument:
    return NormalizedInstrument(
        exchange="NSE",
        segment="FO",
        underlying="NIFTY",
        symbol=f"NIFTY {strike:g}{'CE' if side is Side.CALL else 'PE'}",
        instrument_type="OPTION",
        expiry=_EXPIRY,
        strike=strike,
        option_type=side,
    )


def _prov() -> Provenance:
    return Provenance(
        source="UPSTOX",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=datetime(2028, 8, 3, 10, 0, 1, tzinfo=timezone.utc),
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _reference_for_t(t_years: float) -> datetime:
    """Reference timestamp exactly T ACT/365 years before the fixture expiry."""
    return _EXPIRY_MIDNIGHT - timedelta(seconds=t_years * _SECONDS_PER_YEAR_ACT_365)


def _ctx(
    *,
    t_years: float,
    risk_free: float = 0.05,
    dividend: float | None = None,
) -> CalculationContext:
    return CalculationContext(
        reference_timestamp=_reference_for_t(t_years),
        risk_free_rate=risk_free,
        dividend_yield=dividend,
        model_version="1.0.0",
        calculation_version="1.0.0",
    )


_UNSET = object()


def _md(
    *,
    side: Side,
    spot: float,
    strike: float,
    t_years: float,
    risk_free: float = 0.05,
    dividend: float | None = None,
    sigma: float | None = None,
    market_price: float | None = None,
    quality: QualityState | None = QualityState.EXCELLENT,
    prov: object = _UNSET,
) -> OptionMarketData:
    return OptionMarketData(
        instrument=_option_instrument(side=side, strike=strike),
        spot=spot,
        market_price=market_price,
        implied_volatility=sigma,
        market_timestamp=datetime(2028, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        received_timestamp=datetime(2028, 9, 1, 10, 0, 1, tzinfo=timezone.utc),
        data_mode=DataMode.BROKER_SNAPSHOT,
        quality=quality,
        provenance=prov if prov is not _UNSET else _prov(),
    )


def _run(boundary, engine, md: OptionMarketData, ctx: CalculationContext) -> QuantResult:
    boundary.register(engine)
    return boundary.run(engine.calculation_id, md, ctx)


def _run_pricing(md: OptionMarketData, ctx: CalculationContext) -> QuantResult:
    return _run(QuantitativeEngineBoundary(), BlackScholesMertonPricingEngine(), md, ctx)


def _run_iv(md: OptionMarketData, ctx: CalculationContext) -> QuantResult:
    return _run(
        QuantitativeEngineBoundary(), BlackScholesMertonImpliedVolatilityEngine(), md, ctx
    )


def _assert_price(result: QuantResult, expected: float, rel: float = 1e-9) -> None:
    assert result.status is CalculationStatus.SUCCESS
    assert result.values is not None
    assert result.values["price"] == pytest.approx(expected, rel=rel)


# ---------------------------------------------------------------------------
# 1. Pricing — golden values (independent reference)
# ---------------------------------------------------------------------------


class TestPricingGolden:
    @pytest.mark.parametrize(
        "name,side,spot,strike,t,sigma,r,q,expected",
        GOLDEN_PRICES,
        ids=[g[0] for g in GOLDEN_PRICES],
    )
    def test_golden_fixture(self, name, side, spot, strike, t, sigma, r, q, expected):
        md = _md(side=side, spot=spot, strike=strike, sigma=sigma, t_years=t,
                 risk_free=r, dividend=q if q else None)
        _assert_price(
            _run_pricing(md, _ctx(t_years=t, risk_free=r, dividend=q if q else None)),
            expected,
        )

    def test_atm_call_matches_textbook_anchor(self):
        # Classic reference: S=K=100, r=5%, sigma=20%, T=1 → call ≈ 10.4506
        md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        result = _run_pricing(md, _ctx(t_years=1.0))
        assert result.values["price"] == pytest.approx(10.4506, abs=1e-4)

    def test_price_agrees_with_verified_legacy_implementation(self):
        # Cross-implementation check against the verified Phase-7.19B module
        # (a different codebase — not the module under test).
        from app.services.historical_greeks import bs_price

        for (name, side, spot, strike, t, sigma, r, q, expected) in GOLDEN_PRICES:
            legacy = bs_price(
                "CE" if side is Side.CALL else "PE", spot, strike, t, sigma, r, q
            )
            md = _md(side=side, spot=spot, strike=strike, sigma=sigma, t_years=t,
                     risk_free=r, dividend=q if q else None)
            result = _run_pricing(md, _ctx(t_years=t, risk_free=r, dividend=q if q else None))
            assert result.values["price"] == pytest.approx(legacy, rel=1e-12)

    def test_pure_function_returns_float(self):
        value = black_scholes_merton_price(
            option_type=Side.CALL, spot=100.0, strike=100.0, time_to_expiry=1.0,
            volatility=0.2, risk_free_rate=0.05, dividend_yield=0.0,
        )
        assert isinstance(value, float)
        assert math.isfinite(value)


# ---------------------------------------------------------------------------
# 2. Expiry / near-expiry / zero-volatility conventions
# ---------------------------------------------------------------------------


class TestPricingDegenerateConventions:
    def test_terminal_price_is_intrinsic_itm(self):
        # reference == expiry midnight ⇒ T == 0
        ctx = CalculationContext(reference_timestamp=_EXPIRY_MIDNIGHT, risk_free_rate=0.05)
        call = _run_pricing(_md(side=Side.CALL, spot=105, strike=100, sigma=0.2, t_years=0.0), ctx)
        put = _run_pricing(_md(side=Side.PUT, spot=105, strike=100, sigma=0.2, t_years=0.0), ctx)
        assert call.status is CalculationStatus.SUCCESS
        assert call.values["price"] == pytest.approx(5.0, abs=1e-12)
        assert put.values["price"] == pytest.approx(0.0, abs=1e-12)

    def test_terminal_price_is_intrinsic_otm(self):
        ctx = CalculationContext(reference_timestamp=_EXPIRY_MIDNIGHT, risk_free_rate=0.05)
        call = _run_pricing(_md(side=Side.CALL, spot=95, strike=100, sigma=0.2, t_years=0.0), ctx)
        put = _run_pricing(_md(side=Side.PUT, spot=95, strike=100, sigma=0.2, t_years=0.0), ctx)
        assert call.values["price"] == pytest.approx(0.0, abs=1e-12)
        assert put.values["price"] == pytest.approx(5.0, abs=1e-12)

    def test_near_expiry_price_finite_and_close_to_intrinsic(self):
        t = 1e-5  # ~9 minutes
        md = _md(side=Side.CALL, spot=101, strike=100, sigma=0.2, t_years=t)
        result = _run_pricing(md, _ctx(t_years=t))
        assert result.status is CalculationStatus.SUCCESS
        assert math.isfinite(result.values["price"])
        assert result.values["price"] == pytest.approx(1.0, abs=5e-3)

    def test_zero_volatility_forward_convention(self):
        # sigma == 0 ⇒ max(S·e^(−qT) − K·e^(−rT), 0) — never a division by zero
        md = _md(side=Side.CALL, spot=105, strike=100, sigma=0.0, t_years=1.0)
        result = _run_pricing(md, _ctx(t_years=1.0))
        expected = 105.0 * math.exp(0.0) - 100.0 * math.exp(-0.05)
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["price"] == pytest.approx(expected, rel=1e-12)

    def test_zero_volatility_otm_forward_is_zero(self):
        md = _md(side=Side.CALL, spot=90, strike=100, sigma=0.0, t_years=1.0)
        result = _run_pricing(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["price"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# 3. Input validation
# ---------------------------------------------------------------------------


class TestPricingInputValidation:
    def test_pure_function_rejects_invalid_inputs(self):
        good = dict(option_type=Side.CALL, spot=100.0, strike=100.0,
                    time_to_expiry=1.0, volatility=0.2, risk_free_rate=0.05,
                    dividend_yield=0.0)
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "spot": -1.0})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "spot": 0.0})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "strike": 0.0})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "time_to_expiry": -0.1})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "volatility": -0.1})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "volatility": float("nan")})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "spot": float("inf")})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "risk_free_rate": float("nan")})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "option_type": "NOT_A_SIDE"})
        with pytest.raises(ValueError):
            black_scholes_merton_price(**{**good, "dividend_yield": float("inf")})

    def test_missing_volatility_is_unavailable(self):
        md = _md(side=Side.CALL, spot=100, strike=100, sigma=None, t_years=1.0)
        result = _run_pricing(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)
        assert result.values is None


# ---------------------------------------------------------------------------
# 4. Put-call parity (hard mathematical invariant)
# ---------------------------------------------------------------------------


class TestPutCallParity:
    @pytest.mark.parametrize("spot", [90.0, 100.0, 110.0])
    @pytest.mark.parametrize("t", [7 / 365.0, 0.25, 1.0, 2.0])
    @pytest.mark.parametrize("sigma", [0.1, 0.3, 0.6])
    @pytest.mark.parametrize("r,q", [(0.0, 0.0), (0.05, 0.0), (0.05, 0.02), (0.07, 0.03)])
    def test_call_minus_put_equals_forward_relation(self, spot, t, sigma, r, q):
        strike = 100.0
        call = _run_pricing(_md(side=Side.CALL, spot=spot, strike=strike, sigma=sigma,
                                t_years=t, risk_free=r, dividend=q if q else None),
                            _ctx(t_years=t, risk_free=r, dividend=q if q else None))
        put = _run_pricing(_md(side=Side.PUT, spot=spot, strike=strike, sigma=sigma,
                               t_years=t, risk_free=r, dividend=q if q else None),
                           _ctx(t_years=t, risk_free=r, dividend=q if q else None))
        lhs = call.values["price"] - put.values["price"]
        rhs = spot * math.exp(-q * t) - strike * math.exp(-r * t)
        assert lhs == pytest.approx(rhs, abs=1e-9)


# ---------------------------------------------------------------------------
# 5. Monotonicity properties
# ---------------------------------------------------------------------------


class TestMonotonicity:
    def test_price_non_decreasing_in_volatility(self):
        for side in (Side.CALL, Side.PUT):
            prices = []
            for sigma in (0.05, 0.1, 0.2, 0.4, 0.6, 0.8):
                md = _md(side=side, spot=100, strike=100, sigma=sigma, t_years=1.0)
                prices.append(_run_pricing(md, _ctx(t_years=1.0)).values["price"])
            for lo, hi in zip(prices, prices[1:]):
                assert hi >= lo - 1e-12

    def test_call_price_non_decreasing_in_spot(self):
        prices = []
        for spot in (80.0, 90.0, 100.0, 110.0, 120.0):
            md = _md(side=Side.CALL, spot=spot, strike=100, sigma=0.2, t_years=1.0)
            prices.append(_run_pricing(md, _ctx(t_years=1.0)).values["price"])
        for lo, hi in zip(prices, prices[1:]):
            assert hi >= lo - 1e-12

    def test_put_price_non_increasing_in_spot(self):
        prices = []
        for spot in (80.0, 90.0, 100.0, 110.0, 120.0):
            md = _md(side=Side.PUT, spot=spot, strike=100, sigma=0.2, t_years=1.0)
            prices.append(_run_pricing(md, _ctx(t_years=1.0)).values["price"])
        for lo, hi in zip(prices, prices[1:]):
            assert lo >= hi - 1e-12


# ---------------------------------------------------------------------------
# 6. Greeks consistency (Day-15 engine = authoritative derivative reference)
# ---------------------------------------------------------------------------


class TestGreeksConsistency:
    def _price(self, side, spot, strike, t, sigma, r, q):
        return black_scholes_merton_price(
            option_type=side, spot=spot, strike=strike, time_to_expiry=t,
            volatility=sigma, risk_free_rate=r, dividend_yield=q,
        )

    def _greeks(self, side, spot, strike, t, sigma, r, q):
        return black_scholes_merton_greeks(
            option_type=side, spot=spot, strike=strike, time_to_expiry=t,
            volatility=sigma, risk_free_rate=r, dividend_yield=q,
        )

    def test_delta_matches_price_sensitivity(self):
        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-4
        for side in (Side.CALL, Side.PUT):
            num = (self._price(side, S + h, K, T, sig, r, q)
                   - self._price(side, S - h, K, T, sig, r, q)) / (2 * h)
            model = self._greeks(side, S, K, T, sig, r, q)["delta"]
            assert model == pytest.approx(num, abs=1e-3)

    def test_gamma_matches_second_derivative(self):
        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-2
        model = self._greeks(Side.CALL, S, K, T, sig, r, q)["gamma"]
        d_plus = (self._price(Side.CALL, S + h + 1e-4, K, T, sig, r, q)
                  - self._price(Side.CALL, S + h - 1e-4, K, T, sig, r, q)) / (2 * 1e-4)
        d_minus = (self._price(Side.CALL, S - h + 1e-4, K, T, sig, r, q)
                   - self._price(Side.CALL, S - h - 1e-4, K, T, sig, r, q)) / (2 * 1e-4)
        gamma_fd = (d_plus - d_minus) / (2 * h)
        assert model == pytest.approx(gamma_fd, rel=0.02)

    def test_vega_matches_vol_sensitivity(self):
        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-4
        for side in (Side.CALL, Side.PUT):
            num = (self._price(side, S, K, T, sig + h, r, q)
                   - self._price(side, S, K, T, sig - h, r, q)) / (2 * h)
            model = self._greeks(side, S, K, T, sig, r, q)["vega"]
            assert model == pytest.approx(num, rel=1e-3)

    def test_rho_matches_rate_sensitivity(self):
        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-4
        for side in (Side.CALL, Side.PUT):
            num = (self._price(side, S, K, T, sig, r + h, q)
                   - self._price(side, S, K, T, sig, r - h, q)) / (2 * h)
            model = self._greeks(side, S, K, T, sig, r, q)["rho"]
            assert model == pytest.approx(num, abs=5e-2)

    def test_theta_matches_time_decay(self):
        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-3
        for side in (Side.CALL, Side.PUT):
            d_price_dT = (self._price(side, S, K, T + h, sig, r, q)
                          - self._price(side, S, K, T - h, sig, r, q)) / (2 * h)
            model = self._greeks(side, S, K, T, sig, r, q)["theta"]
            assert model == pytest.approx(-d_price_dT, abs=1e-2)


# ---------------------------------------------------------------------------
# 7. IV — round trips (known σ → price → recovered σ)
# ---------------------------------------------------------------------------


class TestIvRoundTrips:
    @pytest.mark.parametrize(
        "name,side,spot,strike,t,sigma,r,q,market_price",
        GOLDEN_PRICES,
        ids=[g[0] for g in GOLDEN_PRICES],
    )
    def test_round_trip_recovers_originating_volatility(
        self, name, side, spot, strike, t, sigma, r, q, market_price
    ):
        md = _md(side=side, spot=spot, strike=strike, market_price=market_price,
                 t_years=t, risk_free=r, dividend=q if q else None)
        result = _run_iv(md, _ctx(t_years=t, risk_free=r, dividend=q if q else None))
        assert result.status is CalculationStatus.SUCCESS
        assert result.values is not None
        assert set(result.values.keys()) == {"implied_volatility"}
        assert result.values["implied_volatility"] == pytest.approx(sigma, abs=1e-6)

    def test_iv_is_decimal_fraction_not_percentage_points(self):
        # σ = 0.1824 must come back as ≈ 0.1824, never 18.24
        sigma = 0.1824
        md_price = _md(side=Side.CALL, spot=100, strike=100, sigma=sigma, t_years=1.0)
        price = _run_pricing(md_price, _ctx(t_years=1.0)).values["price"]
        md_iv = _md(side=Side.CALL, spot=100, strike=100, market_price=price, t_years=1.0)
        result = _run_iv(md_iv, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        iv = result.values["implied_volatility"]
        assert iv == pytest.approx(sigma, abs=1e-6)
        assert iv < 1.0


# ---------------------------------------------------------------------------
# 8. IV — bounds and failure taxonomy
# ---------------------------------------------------------------------------


class TestIvBoundsAndTaxonomy:
    def test_below_lower_bound_is_invalid(self):
        # ITM call: market 2.0 is far below the forward intrinsic lower bound
        md = _md(side=Side.CALL, spot=110, strike=100, market_price=2.0, t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.INVALID_INPUT
        assert any(i.code is CalculationIssueCode.BELOW_LOWER_BOUND for i in result.issues)
        assert result.values is None

    def test_above_theoretical_max_is_invalid(self):
        # Put upper bound = K·e^(−rT) ≈ 95.12; market 99 is impossible
        md = _md(side=Side.PUT, spot=100, strike=100, market_price=99.0, t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.INVALID_INPUT
        assert any(i.code is CalculationIssueCode.ABOVE_THEORETICAL_MAX for i in result.issues)
        assert result.values is None

    def test_at_lower_bound_solves_to_zero_volatility(self):
        # market == forward intrinsic ⇒ σ = 0.0 is the exact model inverse
        lower = 110.0 * math.exp(0.0) - 100.0 * math.exp(-0.05)
        md = _md(side=Side.CALL, spot=110, strike=100, market_price=lower, t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["implied_volatility"] == 0.0

    def test_slightly_above_lower_bound_solves_to_small_positive_vol(self):
        # A quote epsilon above the forward-intrinsic bound has a real root;
        # deep-ITM price approaches the bound quadratically in σ, so the root
        # is small-but-not-tiny — the solver must find it, never guess 0.
        lower = 110.0 * math.exp(0.0) - 100.0 * math.exp(-0.05)
        md = _md(side=Side.CALL, spot=110, strike=100, market_price=lower + 1e-6, t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert 0.0 < result.values["implied_volatility"] < 0.1

    def test_expired_contract_is_unavailable(self):
        # reference == expiry midnight ⇒ T == 0 ⇒ IV is undefined
        ctx = CalculationContext(reference_timestamp=_EXPIRY_MIDNIGHT, risk_free_rate=0.05)
        md = _md(side=Side.CALL, spot=105, strike=100, market_price=5.0, t_years=0.0)
        result = _run_iv(md, ctx)
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.EXPIRED for i in result.issues)
        assert result.values is None

    def test_missing_market_price_is_unavailable(self):
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=None, t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)

    def test_zero_market_price_is_invalid(self):
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=0.0, t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.INVALID_INPUT
        assert result.values is None

    def test_no_bracket_band_is_reported(self):
        # A short-dated ATM call's price at σ=10 is ≈ 51; a market quote of 90
        # is below the theoretical max (100) but above any achievable model
        # price in the documented domain [0, 10] → NO_BRACKET, never a guess.
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=90.0,
                 t_years=7 / 365.0)
        result = _run_iv(md, _ctx(t_years=7 / 365.0))
        assert result.status is CalculationStatus.FAILED
        assert any(i.code is CalculationIssueCode.NO_BRACKET for i in result.issues)
        assert result.values is None

    def test_convergence_failure_is_reported(self):
        # A single Brent iteration can never meet the documented tolerances →
        # CONVERGENCE_FAILED is reported deterministically, never a guess.
        solve = implied_volatility_solve(
            option_type=Side.CALL, spot=100.0, strike=100.0, time_to_expiry=1.0,
            market_price=10.450583572186, risk_free_rate=0.05, dividend_yield=0.0,
            max_iterations=1,
        )
        assert solve.outcome is IvSolverOutcome.CONVERGENCE_FAILED
        assert solve.sigma is None


# ---------------------------------------------------------------------------
# 9. IV solver input validation (pure function)
# ---------------------------------------------------------------------------


class TestIvInputValidation:
    def test_pure_solver_rejects_invalid_scalars(self):
        good = dict(option_type=Side.CALL, spot=100.0, strike=100.0,
                    time_to_expiry=1.0, market_price=10.0, risk_free_rate=0.05,
                    dividend_yield=0.0)
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "spot": 0.0})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "strike": -1.0})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "time_to_expiry": -0.5})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "market_price": 0.0})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "market_price": -3.0})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "risk_free_rate": float("nan")})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "market_price": float("inf")})
        with pytest.raises(ValueError):
            implied_volatility_solve(**{**good, "option_type": "BOGUS"})

    def test_zero_time_to_expiry_is_expired(self):
        # pure-level: solver treats T == 0 as EXPIRED (no formula at T=0)
        solve = implied_volatility_solve(
            option_type=Side.CALL, spot=100.0, strike=100.0, time_to_expiry=0.0,
            market_price=5.0, risk_free_rate=0.05, dividend_yield=0.0,
        )
        assert solve.outcome is IvSolverOutcome.EXPIRED
        assert solve.sigma is None

    def test_negative_time_to_expiry_raises(self):
        with pytest.raises(ValueError):
            implied_volatility_solve(
                option_type=Side.CALL, spot=100.0, strike=100.0,
                time_to_expiry=-0.5, market_price=5.0, risk_free_rate=0.05,
                dividend_yield=0.0,
            )


# ---------------------------------------------------------------------------
# 10. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_pricing_inputs_identical_results(self):
        md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        ctx = _ctx(t_years=1.0)
        assert _run_pricing(md, ctx) == _run_pricing(md, ctx)

    def test_identical_iv_inputs_identical_results(self):
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                 t_years=1.0)
        ctx = _ctx(t_years=1.0)
        assert _run_iv(md, ctx) == _run_iv(md, ctx)

    def test_volatility_change_changes_price(self):
        r_low = _run_pricing(_md(side=Side.CALL, spot=100, strike=100, sigma=0.1,
                                 t_years=1.0), _ctx(t_years=1.0))
        r_high = _run_pricing(_md(side=Side.CALL, spot=100, strike=100, sigma=0.5,
                                  t_years=1.0), _ctx(t_years=1.0))
        assert r_low.values["price"] != r_high.values["price"]
        assert r_low.values["price"] < r_high.values["price"]

    def test_iv_result_changes_only_with_inputs(self):
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                 t_years=1.0)
        ctx = _ctx(t_years=1.0)
        r1 = _run_iv(md, ctx)
        # different market price ⇒ different recovered IV
        md2 = _md(side=Side.CALL, spot=100, strike=100, market_price=12.0, t_years=1.0)
        r2 = _run_iv(md2, ctx)
        assert r1.status is CalculationStatus.SUCCESS
        assert r1.values["implied_volatility"] != r2.values["implied_volatility"]


# ---------------------------------------------------------------------------
# 11. Quality propagation (Day-12 state consumed — never recomputed)
# ---------------------------------------------------------------------------


class TestQualityPropagation:
    @pytest.mark.parametrize("engine_kind", ["pricing", "iv"])
    @pytest.mark.parametrize("q", [QualityState.EXCELLENT, QualityState.GOOD, QualityState.DEGRADED])
    def test_quality_permitted_and_preserved(self, engine_kind, q):
        if engine_kind == "pricing":
            md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0, quality=q)
            result = _run_pricing(md, _ctx(t_years=1.0))
        else:
            md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                     t_years=1.0, quality=q)
            result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.input_quality is q

    @pytest.mark.parametrize("engine_kind", ["pricing", "iv"])
    def test_insufficient_quality_blocked_before_engine(self, engine_kind):
        if engine_kind == "pricing":
            md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0,
                     quality=QualityState.INSUFFICIENT)
            result = _run_pricing(md, _ctx(t_years=1.0))
        else:
            md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                     t_years=1.0, quality=QualityState.INSUFFICIENT)
            result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.INSUFFICIENT_QUALITY for i in result.issues)
        assert result.values is None

    @pytest.mark.parametrize("engine_kind", ["pricing", "iv"])
    def test_missing_provenance_blocked_before_engine(self, engine_kind):
        if engine_kind == "pricing":
            md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0, prov=None)
            result = _run_pricing(md, _ctx(t_years=1.0))
        else:
            md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                     t_years=1.0, prov=None)
            result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_PROVENANCE for i in result.issues)


# ---------------------------------------------------------------------------
# 12. Provenance & versioning
# ---------------------------------------------------------------------------


class TestProvenanceVersioning:
    def test_pricing_provenance_and_versions_preserved(self):
        md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        result = _run_pricing(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.provenance == md.provenance
        assert result.reference_timestamp is not None
        assert result.model_version == PRICING_MODEL_VERSION
        assert result.calculation_version == PRICING_CALCULATION_VERSION
        assert result.calculation_id == PRICING_CALCULATION_ID

    def test_iv_provenance_and_versions_preserved(self):
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                 t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.provenance == md.provenance
        assert result.model_version == IV_MODEL_VERSION
        assert result.calculation_version == IV_CALCULATION_VERSION
        assert result.calculation_id == IV_CALCULATION_ID

    def test_shared_model_family_with_day15(self):
        # pricing/IV must share the SAME canonical model identity as Day 15 —
        # never an inconsistent label implying a different convention
        engine = BlackScholesMertonPricingEngine()
        assert engine.model == BLACK_SCHOLES_MERTON_EUROPEAN
        iv_engine = BlackScholesMertonImpliedVolatilityEngine()
        assert iv_engine.model == BLACK_SCHOLES_MERTON_EUROPEAN

    def test_model_iv_never_overwrites_broker_observation(self):
        broker = GreeksObservation(
            iv=0.2, delta=0.61, gamma=0.019, theta=-6.0, vega=37.1, source="BROKER",
        )
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                 t_years=1.0)
        result = _run_iv(md, _ctx(t_years=1.0))
        assert broker.source == "BROKER"
        # the model result identifies itself via calculation_id/versions — the
        # broker observation object is untouched and distinct
        assert result.calculation_id == IV_CALCULATION_ID
        assert result.model_version is not None


# ---------------------------------------------------------------------------
# 13. Boundary integration
# ---------------------------------------------------------------------------


class TestBoundaryIntegration:
    def test_pricing_registers_and_routes(self):
        boundary = QuantitativeEngineBoundary()
        boundary.register(BlackScholesMertonPricingEngine())
        assert PRICING_CALCULATION_ID in boundary.available_calculations()
        md = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        result = boundary.run(PRICING_CALCULATION_ID, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert set(result.values.keys()) == {"price"}

    def test_iv_registers_and_routes(self):
        boundary = QuantitativeEngineBoundary()
        boundary.register(BlackScholesMertonImpliedVolatilityEngine())
        assert IV_CALCULATION_ID in boundary.available_calculations()
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                 t_years=1.0)
        result = boundary.run(IV_CALCULATION_ID, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert set(result.values.keys()) == {"implied_volatility"}

    def test_all_three_engines_coexist_on_one_boundary(self):
        from app.quant.greeks import CALCULATION_ID as GREEKS_ID, BlackScholesEuropeanGreeksEngine

        boundary = QuantitativeEngineBoundary()
        boundary.register(BlackScholesEuropeanGreeksEngine())
        boundary.register(BlackScholesMertonPricingEngine())
        boundary.register(BlackScholesMertonImpliedVolatilityEngine())
        assert set(boundary.available_calculations()) == {
            GREEKS_ID, PRICING_CALCULATION_ID, IV_CALCULATION_ID,
        }
        md_g = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        assert boundary.run(GREEKS_ID, md_g, _ctx(t_years=1.0)).succeeded
        md_p = _md(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        assert boundary.run(PRICING_CALCULATION_ID, md_p, _ctx(t_years=1.0)).succeeded
        md_i = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                   t_years=1.0)
        assert boundary.run(IV_CALCULATION_ID, md_i, _ctx(t_years=1.0)).succeeded


# ---------------------------------------------------------------------------
# 14. Numerical stability / edge cases
# ---------------------------------------------------------------------------


class TestNumericalStability:
    def test_deep_itm_otm_prices_finite_and_bounded(self):
        for side, spot in [(Side.CALL, 1e6), (Side.CALL, 1e-6), (Side.PUT, 1e6), (Side.PUT, 1e-6)]:
            md = _md(side=side, spot=spot, strike=100.0, sigma=0.3, t_years=1.0)
            result = _run_pricing(md, _ctx(t_years=1.0))
            assert result.status is CalculationStatus.SUCCESS
            assert math.isfinite(result.values["price"])

    def test_tiny_and_huge_volatility_prices_finite(self):
        for sigma in (1e-6, 10.0):
            md = _md(side=Side.CALL, spot=100, strike=100, sigma=sigma, t_years=1.0)
            result = _run_pricing(md, _ctx(t_years=1.0))
            assert result.status is CalculationStatus.SUCCESS
            assert math.isfinite(result.values["price"])

    def test_iv_for_deep_itm_and_otm_quotes_finite(self):
        # spot 120/80 quotes priced from the model at σ=0.3 round-trip cleanly
        for side, spot in [(Side.CALL, 120.0), (Side.PUT, 120.0),
                           (Side.CALL, 80.0), (Side.PUT, 80.0)]:
            price = black_scholes_merton_price(
                option_type=side, spot=spot, strike=100.0, time_to_expiry=0.5,
                volatility=0.3, risk_free_rate=0.07, dividend_yield=0.03,
            )
            md = _md(side=side, spot=spot, strike=100.0, market_price=price,
                     t_years=0.5, risk_free=0.07, dividend=0.03)
            result = _run_iv(md, _ctx(t_years=0.5, risk_free=0.07, dividend=0.03))
            assert result.status is CalculationStatus.SUCCESS
            assert result.values["implied_volatility"] == pytest.approx(0.3, abs=1e-6)


# ---------------------------------------------------------------------------
# 15. Security & broker neutrality (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    @pytest.mark.parametrize("module_name", ["pricing.py", "iv.py"])
    def test_module_has_no_clock_or_io_imports(self, module_name):
        import ast as _ast
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "app" / "quant" / module_name
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

    def test_results_never_leak_credentials(self):
        secret = "sk_live_upstox_secret_xyz"
        md = _md(side=Side.CALL, spot=100, strike=100, market_price=10.450583572186,
                 t_years=1.0)
        md = OptionMarketData(
            instrument=md.instrument, spot=md.spot, market_price=10.450583572186,
            market_timestamp=md.market_timestamp, received_timestamp=md.received_timestamp,
            data_mode=md.data_mode, quality=md.quality,
            provenance=Provenance(
                source="UPSTOX", collection_mode=DataMode.BROKER_SNAPSHOT.value,
                received_at=md.received_timestamp, normalization_version="1.0.0",
                contract_version="1.0.0", transformation_id=None,
            ),
        )
        result = _run_iv(md, _ctx(t_years=1.0))
        assert secret not in str(result)
        assert "access_token" not in str(result)
        assert "authorization" not in str(result)
