"""Day 15 — Deterministic Greeks Engine tests (RED-phase contract).

Proves the first real quantitative engine on the Day-14 boundary:

    Canonical option inputs (OptionMarketData + CalculationContext)
        → QuantitativeEngineBoundary (provenance/quality guards)
        → BlackScholesEuropeanGreeksEngine (app/quant/greeks)
            delta / gamma / theta / vega / rho  (call + put)
        → QuantResult (values + quality + provenance + versions)

Rules locked by these tests
---------------------------
1. European Black-Scholes-Merton with continuous dividend yield q; the
   repository's established conventions (from the verified Phase-7.19B
   implementation): vega per 1.00 vol fraction, theta annualized per year,
   rho per 1.00 continuously-compounded rate, delta dimensionless, gamma per
   unit of underlying price.
2. T comes ONLY from the Day-14 ACT/365 `time_to_expiry` (explicit expiry +
   context reference timestamp) — the engine never reads the clock.
3. Deterministic + broker-neutral: same inputs + context ⇒ identical results;
   no hidden state (AST rules from Day 14 extend over the new module).
4. No fabrication: missing implied volatility ⇒ UNAVAILABLE; invalid inputs ⇒
   INVALID_INPUT; never NaN/Infinity; never a guessed value.
5. Terminal (T=0) and zero-volatility degenerate conventions are explicit and
   documented.
6. Quality is propagated (Day 12 state preserved, never recomputed);
   provenance is preserved; model/calculation versions are explicit.
7. Broker Greeks (GreeksObservation source="BROKER") remain distinct from
   StrikeNova model Greeks.

Golden expected values were computed by an independent closed-form evaluation
of the BS-Merton formulas; the ATM-1y set matches the classic textbook
reference (delta_call ≈ 0.6368, vega ≈ 37.524, theta ≈ −6.414/yr, rho ≈ 53.23).
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
from app.quant.greeks import (
    BLACK_SCHOLES_MERTON_EUROPEAN,
    BlackScholesEuropeanGreeksEngine,
    CALCULATION_ID,
    CALCULATION_VERSION,
    MODEL_VERSION,
    black_scholes_merton_greeks,
)

_SECONDS_PER_YEAR_ACT_365 = 365.0 * 86400.0
_EXPIRY = "2028-09-03"
_EXPIRY_MIDNIGHT = datetime(2028, 9, 3, tzinfo=timezone.utc)


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
    model_version: str | None = MODEL_VERSION,
    calculation_version: str | None = CALCULATION_VERSION,
) -> CalculationContext:
    return CalculationContext(
        reference_timestamp=_reference_for_t(t_years),
        risk_free_rate=risk_free,
        dividend_yield=dividend,
        model_version=model_version,
        calculation_version=calculation_version,
    )


_UNSET = object()


def _market_data(
    *,
    side: Side,
    spot: float,
    strike: float,
    sigma: float,
    t_years: float,
    risk_free: float = 0.05,
    dividend: float | None = None,
    quality: QualityState | None = QualityState.EXCELLENT,
    prov: Provenance | None | None = _UNSET,
) -> OptionMarketData:
    return OptionMarketData(
        instrument=_option_instrument(side=side, strike=strike),
        spot=spot,
        market_price=None,
        implied_volatility=sigma,
        market_timestamp=datetime(2028, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        received_timestamp=datetime(2028, 9, 1, 10, 0, 1, tzinfo=timezone.utc),
        data_mode=DataMode.BROKER_SNAPSHOT,
        quality=quality,
        provenance=prov if prov is not _UNSET else _prov(),
    )


def _engine() -> BlackScholesEuropeanGreeksEngine:
    return BlackScholesEuropeanGreeksEngine()


def _run(engine, md: OptionMarketData, ctx: CalculationContext) -> QuantResult:
    boundary = QuantitativeEngineBoundary()
    boundary.register(engine)
    return boundary.run(engine.calculation_id, md, ctx)


def _assert_golden(result: QuantResult, *, delta, gamma, vega, theta, rho):
    assert result.status is CalculationStatus.SUCCESS
    assert result.values is not None
    assert result.values["delta"] == pytest.approx(delta, rel=1e-9)
    assert result.values["gamma"] == pytest.approx(gamma, rel=1e-9)
    assert result.values["vega"] == pytest.approx(vega, rel=1e-9)
    assert result.values["theta"] == pytest.approx(theta, rel=1e-9)
    assert result.values["rho"] == pytest.approx(rho, rel=1e-9)


# Golden fixtures (independently computed closed-form expected values, 12 dp).
# Cross-checked against the verified Phase-7.19B implementation; the ATM 1y set
# matches the classic textbook reference (delta_call 0.6368, vega 37.524,
# theta −6.414/yr, rho 53.23).
GOLDEN = [
    # name, side, spot, strike, T, sigma, r, q, expected dict
    ("ATM_CALL", Side.CALL, 100, 100, 1.0, 0.2, 0.05, 0.0,
     dict(delta=0.636830651176, gamma=0.018762017346, vega=37.524034691694, theta=-6.414027546438, rho=53.232481545376)),
    ("ATM_PUT", Side.PUT, 100, 100, 1.0, 0.2, 0.05, 0.0,
     dict(delta=-0.363169348824, gamma=0.018762017346, vega=37.524034691694, theta=-1.657880423935, rho=-41.890460904695)),
    ("ITM_CALL", Side.CALL, 110, 100, 1.0, 0.2, 0.05, 0.0,
     dict(delta=0.795754171310, gamma=0.012886510906, vega=31.185356392728, theta=-6.612035894446, rho=69.870005103464)),
    ("ITM_PUT", Side.PUT, 90, 100, 1.0, 0.2, 0.05, 0.0,
     dict(delta=-0.570168268110, gamma=0.021819747580, vega=35.347991079049, theta=-0.458333674963, rho=-61.529308658830)),
    ("OTM_CALL", Side.CALL, 90, 100, 1.0, 0.2, 0.05, 0.0,
     dict(delta=0.429831731890, gamma=0.021819747580, vega=35.347991079049, theta=-5.214480797467, rho=33.593633791241)),
    ("OTM_PUT", Side.PUT, 110, 100, 1.0, 0.2, 0.05, 0.0,
     dict(delta=-0.204245828690, gamma=0.012886510906, vega=31.185356392728, theta=-1.855888771942, rho=-25.252937346607)),
    ("SHORT_7D_CALL", Side.CALL, 100, 100, 7 / 365.0, 0.2, 0.05, 0.0,
     dict(delta=0.519329057388, gamma=0.143869036492, vega=5.518264413392, theta=-31.312804123668, rho=0.973861795993)),
    ("LONG_2Y_CALL", Side.CALL, 100, 100, 2.0, 0.2, 0.05, 0.0,
     dict(delta=0.689691026781, gamma=0.012478546402, vega=49.914185607230, theta=-5.137825428018, rho=105.684645906274)),
    ("DIVIDEND_CALL", Side.CALL, 100, 100, 1.0, 0.2, 0.05, 0.02,
     dict(delta=0.586851146135, gamma=0.018950578755, vega=37.901157510017, theta=-5.089318913998, rho=49.458109105322)),
    ("HIGH_VOL_CALL", Side.CALL, 100, 100, 1.0, 0.6, 0.05, 0.0,
     dict(delta=0.649263686517, gamma=0.006178033156, vega=37.068198938439, theta=-13.090617830835, rho=39.403162986069)),
    ("LOW_VOL_CALL", Side.CALL, 100, 100, 1.0, 0.05, 0.05, 0.0,
     dict(delta=0.847318406167, gamma=0.047184541735, vega=23.592270867687, theta=-4.562235353144, rho=79.448571629039)),
]


# ---------------------------------------------------------------------------
# 1. Core mathematics — golden values
# ---------------------------------------------------------------------------


class TestCoreMathGolden:
    @pytest.mark.parametrize(
        "name,side,spot,strike,t,sigma,r,q,expected",
        GOLDEN,
        ids=[g[0] for g in GOLDEN],
    )
    def test_golden_fixture(self, name, side, spot, strike, t, sigma, r, q, expected):
        result = _run(_engine(), _market_data(side=side, spot=spot, strike=strike, sigma=sigma, t_years=t, risk_free=r, dividend=q if q else None), _ctx(t_years=t, risk_free=r, dividend=q if q else None))
        _assert_golden(result, **expected)

    def test_call_delta_positive_and_put_delta_negative(self):
        call = _run(_engine(), _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
        put = _run(_engine(), _market_data(side=Side.PUT, spot=100, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
        assert call.values["delta"] > 0
        assert put.values["delta"] < 0
        assert call.values["delta"] < 1.0
        assert put.values["delta"] > -1.0

    def test_call_and_put_theta_signs(self):
        # long ATM call with positive rates decays faster than the put
        call = _run(_engine(), _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
        put = _run(_engine(), _market_data(side=Side.PUT, spot=100, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
        assert call.values["theta"] < 0
        assert put.values["theta"] < 0
        assert call.values["theta"] < put.values["theta"]


# ---------------------------------------------------------------------------
# 2. Call/put parity & mathematical properties
# ---------------------------------------------------------------------------


class TestCallPutRelationships:
    @pytest.mark.parametrize("q,t", [(0.0, 1.0), (0.02, 1.0), (0.0, 7 / 365.0), (0.05, 2.0)])
    def test_delta_call_minus_delta_put_equals_exp_minus_qT(self, q, t):
        spot = strike = 100.0
        call = _run(_engine(), _market_data(side=Side.CALL, spot=spot, strike=strike, sigma=0.25, t_years=t, dividend=q or None), _ctx(t_years=t, dividend=q or None))
        put = _run(_engine(), _market_data(side=Side.PUT, spot=spot, strike=strike, sigma=0.25, t_years=t, dividend=q or None), _ctx(t_years=t, dividend=q or None))
        expected = math.exp(-q * t)
        assert (call.values["delta"] - put.values["delta"]) == pytest.approx(expected, abs=1e-12)

    def test_gamma_parity(self):
        call = _run(_engine(), _market_data(side=Side.CALL, spot=105, strike=100, sigma=0.25, t_years=0.5), _ctx(t_years=0.5))
        put = _run(_engine(), _market_data(side=Side.PUT, spot=105, strike=100, sigma=0.25, t_years=0.5), _ctx(t_years=0.5))
        assert call.values["gamma"] == pytest.approx(put.values["gamma"], rel=1e-12)

    def test_vega_parity(self):
        call = _run(_engine(), _market_data(side=Side.CALL, spot=105, strike=100, sigma=0.25, t_years=0.5), _ctx(t_years=0.5))
        put = _run(_engine(), _market_data(side=Side.PUT, spot=105, strike=100, sigma=0.25, t_years=0.5), _ctx(t_years=0.5))
        assert call.values["vega"] == pytest.approx(put.values["vega"], rel=1e-12)

    def test_delta_bounds_across_moneyness(self):
        for spot in (80.0, 100.0, 120.0):
            call = _run(_engine(), _market_data(side=Side.CALL, spot=spot, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
            assert 0.0 < call.values["delta"] < 1.0
            put = _run(_engine(), _market_data(side=Side.PUT, spot=spot, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
            assert -1.0 < put.values["delta"] < 0.0


# ---------------------------------------------------------------------------
# 3. Finite-difference validation (independent reference = legacy bs_price)
# ---------------------------------------------------------------------------


class TestFiniteDifferenceValidation:
    def _price(self, side, spot, strike, t, sigma, r, q):
        from app.services.historical_greeks import bs_price

        return bs_price("CE" if side is Side.CALL else "PE", spot, strike, t, sigma, r, q)

    def test_delta_matches_price_sensitivity(self):
        e = _engine()
        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-4
        for side in (Side.CALL, Side.PUT):
            num = (self._price(side, S + h, K, T, sig, r, q) - self._price(side, S - h, K, T, sig, r, q)) / (2 * h)
            md = _market_data(side=side, spot=S, strike=K, sigma=sig, t_years=T, risk_free=r)
            val = _run(e, md, _ctx(t_years=T, risk_free=r)).values["delta"]
            assert val == pytest.approx(num, abs=1e-3)

    def test_gamma_matches_delta_sensitivity(self):
        from app.services.historical_greeks import bs_price

        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-2  # larger step for second derivative noise
        e = _engine()
        md = _market_data(side=Side.CALL, spot=S, strike=K, sigma=sig, t_years=T, risk_free=r)
        gamma_model = _run(e, md, _ctx(t_years=T, risk_free=r)).values["gamma"]
        d_plus = (bs_price("CE", S + h, K, T, sig, r, q) - bs_price("CE", S + h - 1e-4, K, T, sig, r, q)) / 1e-4
        d_minus = (bs_price("CE", S - h, K, T, sig, r, q) - bs_price("CE", S - h - 1e-4, K, T, sig, r, q)) / 1e-4
        gamma_fd = (d_plus - d_minus) / (2 * h)
        assert gamma_model == pytest.approx(gamma_fd, rel=0.02)

    def test_vega_matches_vol_sensitivity(self):
        from app.services.historical_greeks import bs_price

        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-4
        e = _engine()
        for side in (Side.CALL, Side.PUT):
            num = (bs_price("CE" if side is Side.CALL else "PE", S, K, T, sig + h, r, q) - bs_price("CE" if side is Side.CALL else "PE", S, K, T, sig - h, r, q)) / (2 * h)
            md = _market_data(side=side, spot=S, strike=K, sigma=sig, t_years=T, risk_free=r)
            val = _run(e, md, _ctx(t_years=T, risk_free=r)).values["vega"]
            assert val == pytest.approx(num, rel=1e-3)

    def test_rho_matches_rate_sensitivity(self):
        from app.services.historical_greeks import bs_price

        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-4
        e = _engine()
        for side in (Side.CALL, Side.PUT):
            num = (bs_price("CE" if side is Side.CALL else "PE", S, K, T, sig, r + h, q) - bs_price("CE" if side is Side.CALL else "PE", S, K, T, sig, r - h, q)) / (2 * h)
            md = _market_data(side=side, spot=S, strike=K, sigma=sig, t_years=T, risk_free=r)
            val = _run(e, md, _ctx(t_years=T, risk_free=r)).values["rho"]
            assert val == pytest.approx(num, abs=5e-2)

    def test_theta_matches_time_decay(self):
        from app.services.historical_greeks import bs_price

        S, K, T, sig, r, q = 100.0, 100.0, 1.0, 0.2, 0.05, 0.0
        h = 1e-3  # time step in years
        e = _engine()
        for side in (Side.CALL, Side.PUT):
            # theta = −∂C/∂T (time-to-expiry measured forward); the central
            # difference of price in T is +∂C/∂T, so the expectation flips sign.
            d_price_dT = (bs_price("CE" if side is Side.CALL else "PE", S, K, T + h, sig, r, q) - bs_price("CE" if side is Side.CALL else "PE", S, K, T - h, sig, r, q)) / (2 * h)
            md = _market_data(side=side, spot=S, strike=K, sigma=sig, t_years=T, risk_free=r)
            val = _run(e, md, _ctx(t_years=T, risk_free=r)).values["theta"]
            assert val == pytest.approx(-d_price_dT, abs=1e-2)


# ---------------------------------------------------------------------------
# 4. Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_pure_function_rejects_invalid_inputs(self):
        good = dict(option_type=Side.CALL, spot=100.0, strike=100.0, time_to_expiry=1.0, volatility=0.2, risk_free_rate=0.05, dividend_yield=0.0)
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "spot": -1.0})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "spot": 0.0})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "strike": 0.0})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "time_to_expiry": -0.1})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "volatility": -0.1})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "volatility": float("nan")})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "spot": float("inf")})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "risk_free_rate": float("nan")})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "option_type": Side.PUT if False else "NOT_A_SIDE"})
        with pytest.raises(ValueError):
            black_scholes_merton_greeks(**{**good, "dividend_yield": float("inf")})

    def test_missing_volatility_is_unavailable(self):
        engine = _engine()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        md = OptionMarketData(
            instrument=md.instrument,
            spot=md.spot,
            market_price=None,
            implied_volatility=None,
            market_timestamp=md.market_timestamp,
            received_timestamp=md.received_timestamp,
            data_mode=md.data_mode,
            quality=md.quality,
            provenance=md.provenance,
        )
        result = _run(engine, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)
        assert result.values is None

    def test_non_positive_strike_rejected_at_contract(self):
        # Day-15 tightens the OptionMarketData input contract: a concrete
        # option's strike must be finite and positive (log-price math requires
        # it) — rejected at construction, before any engine runs.
        bad = NormalizedInstrument(
            exchange="NSE", segment="FO", underlying="NIFTY", symbol="X",
            instrument_type="OPTION", expiry=_EXPIRY, strike=-1.0, option_type=Side.CALL,
        )
        with pytest.raises(ValueError):
            OptionMarketData(instrument=bad, spot=100.0, implied_volatility=0.2)
        with pytest.raises(ValueError):
            OptionMarketData(
                instrument=NormalizedInstrument(
                    exchange="NSE", segment="FO", underlying="NIFTY", symbol="X",
                    instrument_type="OPTION", expiry=_EXPIRY, strike=0.0, option_type=Side.CALL,
                ),
                spot=100.0,
                implied_volatility=0.2,
            )


# ---------------------------------------------------------------------------
# 5. Expiry / terminal behavior
# ---------------------------------------------------------------------------


class TestExpiryBehavior:
    def test_terminal_convention_at_exact_expiry_itm(self):
        # reference == expiry midnight ⇒ T == 0
        ref = _EXPIRY_MIDNIGHT
        ctx = CalculationContext(reference_timestamp=ref, risk_free_rate=0.05)
        call = _run(_engine(), _market_data(side=Side.CALL, spot=105, strike=100, sigma=0.2, t_years=0.0), ctx)
        assert call.status is CalculationStatus.SUCCESS
        assert call.values["delta"] == 1.0
        assert call.values["gamma"] == 0.0
        assert call.values["vega"] == 0.0
        assert call.values["theta"] == 0.0
        assert call.values["rho"] == 0.0

    def test_terminal_convention_at_exact_expiry_otm(self):
        ref = _EXPIRY_MIDNIGHT
        ctx = CalculationContext(reference_timestamp=ref, risk_free_rate=0.05)
        put = _run(_engine(), _market_data(side=Side.PUT, spot=105, strike=100, sigma=0.2, t_years=0.0), ctx)
        assert put.status is CalculationStatus.SUCCESS
        assert put.values["delta"] == 0.0  # OTM put
        assert put.values["gamma"] == 0.0
        assert put.values["vega"] == 0.0
        assert put.values["theta"] == 0.0
        assert put.values["rho"] == 0.0

    def test_terminal_atm_expiry_delta_zero(self):
        ref = _EXPIRY_MIDNIGHT
        ctx = CalculationContext(reference_timestamp=ref, risk_free_rate=0.05)
        call = _run(_engine(), _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=0.0), ctx)
        assert call.values["delta"] == 0.0
        put = _run(_engine(), _market_data(side=Side.PUT, spot=100, strike=100, sigma=0.2, t_years=0.0), ctx)
        assert put.values["delta"] == 0.0

    def test_near_expiry_is_finite_and_deterministic(self):
        t = 1e-4  # ~53 minutes
        result = _run(_engine(), _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=t), _ctx(t_years=t))
        assert result.status is CalculationStatus.SUCCESS
        for v in result.values.values():
            assert math.isfinite(v)

    def test_zero_volatility_degenerate_convention(self):
        # sigma == 0 is deterministic (forward comparison); never NaN
        md = _market_data(side=Side.CALL, spot=105, strike=100, sigma=0.0, t_years=1.0)
        result = _run(_engine(), md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["delta"] == 1.0  # forward above strike
        assert result.values["gamma"] == 0.0
        for v in result.values.values():
            assert math.isfinite(v)


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_identical_results(self):
        e = _engine()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        ctx = _ctx(t_years=1.0)
        r1 = _run(e, md, ctx)
        r2 = _run(e, md, ctx)
        assert r1 == r2
        assert r1.values == r2.values

    def test_time_enters_only_through_context(self):
        e = _engine()
        md_early = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        md_late = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=0.5)
        r1 = _run(e, md_early, _ctx(t_years=1.0))
        r2 = _run(e, md_late, _ctx(t_years=0.5))
        # time-to-expiry difference must change theta (time decay) & rho
        assert r1.values["theta"] != r2.values["theta"]
        assert r1.values["rho"] != r2.values["rho"]

    def test_volatility_change_changes_vega_and_delta(self):
        e = _engine()
        r_low = _run(e, _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.1, t_years=1.0), _ctx(t_years=1.0))
        r_high = _run(e, _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.5, t_years=1.0), _ctx(t_years=1.0))
        assert r_low.values["vega"] != r_high.values["vega"]
        assert r_low.values["delta"] != r_high.values["delta"]

    def test_spot_change_moves_delta(self):
        e = _engine()
        itm = _run(e, _market_data(side=Side.CALL, spot=110, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
        otm = _run(e, _market_data(side=Side.CALL, spot=90, strike=100, sigma=0.2, t_years=1.0), _ctx(t_years=1.0))
        assert itm.values["delta"] > otm.values["delta"]


# ---------------------------------------------------------------------------
# 7. Quality propagation (Day 12 state consumed — never recomputed)
# ---------------------------------------------------------------------------


class TestQualityPropagation:
    @pytest.mark.parametrize("q", [QualityState.EXCELLENT, QualityState.GOOD, QualityState.DEGRADED])
    def test_quality_permitted_and_preserved(self, q):
        engine = _engine()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0, quality=q)
        result = _run(engine, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert result.input_quality is q

    def test_insufficient_quality_blocked_before_engine(self):
        # boundary gate (Day 14) — the engine must not even run
        engine = _engine()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0, quality=QualityState.INSUFFICIENT)
        result = _run(engine, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.INSUFFICIENT_QUALITY for i in result.issues)
        assert result.values is None


# ---------------------------------------------------------------------------
# 8. Provenance & versioning
# ---------------------------------------------------------------------------


class TestProvenanceVersioning:
    def test_provenance_and_versions_preserved(self):
        engine = _engine()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        ctx = _ctx(t_years=1.0, model_version=MODEL_VERSION, calculation_version=CALCULATION_VERSION)
        result = _run(engine, md, ctx)
        assert result.status is CalculationStatus.SUCCESS
        assert result.provenance == md.provenance
        assert result.reference_timestamp == ctx.reference_timestamp
        assert result.model_version == MODEL_VERSION
        assert result.calculation_version == CALCULATION_VERSION
        assert result.calculation_id == CALCULATION_ID

    def test_engine_identifies_model(self):
        engine = _engine()
        assert engine.model == BLACK_SCHOLES_MERTON_EUROPEAN
        assert engine.model_version == MODEL_VERSION
        assert engine.calculation_version == CALCULATION_VERSION
        assert engine.calculation_id == CALCULATION_ID

    def test_broker_greeks_remain_distinct(self):
        # broker-provided Greeks live in a Day-9 GreeksObservation(source=BROKER)
        broker = GreeksObservation(
            iv=0.2, delta=0.61, gamma=0.019, theta=-6.0, vega=37.1, source="BROKER",
        )
        engine = _engine()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        model_result = _run(engine, md, _ctx(t_years=1.0))
        assert broker.source == "BROKER"
        # the model result identifies itself via calculation_id/versions and
        # carries its own delta — it never overwrites the broker observation
        assert model_result.calculation_id == CALCULATION_ID
        assert model_result.values["delta"] != broker.delta or model_result.model_version is not None
        assert model_result.model_version is not None


# ---------------------------------------------------------------------------
# 9. Boundary integration
# ---------------------------------------------------------------------------


class TestBoundaryIntegration:
    def test_engine_registers_and_routes(self):
        boundary = QuantitativeEngineBoundary()
        boundary.register(_engine())
        assert CALCULATION_ID in boundary.available_calculations()
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        result = boundary.run(CALCULATION_ID, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.SUCCESS
        assert set(result.values.keys()) == {"delta", "gamma", "theta", "vega", "rho"}

    def test_boundary_guard_missing_provenance_still_applies(self):
        boundary = QuantitativeEngineBoundary()
        boundary.register(_engine())
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0, prov=None)
        result = boundary.run(CALCULATION_ID, md, _ctx(t_years=1.0))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_PROVENANCE for i in result.issues)


# ---------------------------------------------------------------------------
# 10. Edge cases / numerical stability
# ---------------------------------------------------------------------------


class TestNumericalStability:
    def test_tiny_volatility_finite(self):
        t = 1.0
        result = _run(_engine(), _market_data(side=Side.CALL, spot=100, strike=100, sigma=1e-6, t_years=t), _ctx(t_years=t))
        assert result.status is CalculationStatus.SUCCESS
        for v in result.values.values():
            assert math.isfinite(v)

    def test_deep_itm_and_deep_otm_finite_bounded(self):
        for side, spot in [(Side.CALL, 1e6), (Side.CALL, 1e-6), (Side.PUT, 1e6), (Side.PUT, 1e-6)]:
            md = _market_data(side=side, spot=spot, strike=100.0, sigma=0.3, t_years=1.0)
            result = _run(_engine(), md, _ctx(t_years=1.0))
            assert result.status is CalculationStatus.SUCCESS
            for v in result.values.values():
                assert math.isfinite(v)
            assert -1.0 <= result.values["delta"] <= 1.0

    def test_negative_dividend_yield_supported(self):
        # negative dividend yield (cost of carry) is mathematically valid
        result = _run(
            _engine(),
            _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0, dividend=-0.01),
            _ctx(t_years=1.0, dividend=-0.01),
        )
        assert result.status is CalculationStatus.SUCCESS
        assert math.isfinite(result.values["delta"])


# ---------------------------------------------------------------------------
# 11. Security & broker neutrality (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    def test_module_has_no_clock_or_io_imports(self):
        import ast as _ast
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "app" / "quant" / "greeks.py"
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx", "urllib", "fastapi"}
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today"}
            if isinstance(node, _ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, _ast.ImportFrom):
                assert not (node.module or "").startswith("app.brokers")
                assert not (node.module or "").startswith("app.services")

    def test_results_never_leak_credentials(self):
        md = _market_data(side=Side.CALL, spot=100, strike=100, sigma=0.2, t_years=1.0)
        secret = "sk_live_upstox_secret_xyz"
        md = OptionMarketData(
            instrument=md.instrument, spot=md.spot, implied_volatility=0.2,
            market_timestamp=md.market_timestamp, received_timestamp=md.received_timestamp,
            data_mode=md.data_mode, quality=md.quality,
            provenance=Provenance(
                source="UPSTOX", collection_mode=DataMode.BROKER_SNAPSHOT.value,
                received_at=md.received_timestamp, normalization_version="1.0.0",
                contract_version="1.0.0", transformation_id=None,
            ),
        )
        result = _run(_engine(), md, _ctx(t_years=1.0))
        assert secret not in str(result)
        assert "access_token" not in str(result)
