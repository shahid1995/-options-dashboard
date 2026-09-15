"""Black-Scholes-Merton Greeks engine (Day 15).

The first real quantitative engine on the Day-14 boundary: deterministic,
broker-neutral European option Greeks (delta / gamma / theta / vega / rho for
call and put) registered through :class:`QuantitativeEngineBoundary`.

    Canonical option inputs (OptionMarketData + CalculationContext)
        → QuantitativeEngineBoundary (provenance / quality guards)
        → BlackScholesEuropeanGreeksEngine
        → QuantResult {delta, gamma, theta, vega, rho}

Mathematical model
------------------
European Black-Scholes-Merton with a continuous dividend yield ``q`` (the
formulation already verified in ``app.services.historical_greeks`` — that
DB-coupled legacy module is NOT modified; its math is ported here as a pure,
DB-free, broker-free engine).  With ``T`` in years, ``r``/``q``/``sigma`` as
decimal fractions::

    d1 = (ln S − ln K + (r − q + σ²/2)·T) / (σ·√T)
    d2 = d1 − σ·√T
    φ = N'(d1)   (normal density);  N = normal CDF via math.erf
    dfQ = e^(−qT);  dfR = e^(−rT)
    Call delta = dfQ·N(d1)      Put delta = dfQ·(N(d1) − 1)
    gamma (both) = dfQ·φ / (S·σ·√T)
    vega  (both) = S·dfQ·φ·√T            per 1.00 vol fraction (σ = 0.18 ⇒ 18%)
    theta (per year, annualized):
        call = −(S·dfQ·φ·σ)/(2√T) − r·K·dfR·N(d2)  + q·S·dfQ·N(d1)
        put  = −(S·dfQ·φ·σ)/(2√T) + r·K·dfR·N(−d2) − q·S·dfQ·N(−d1)
    rho (per 1.00 continuously-compounded rate):
        call = +K·T·dfR·N(d2)    put = −K·T·dfR·N(−d2)

Units (documented, tested)
--------------------------
* delta — dimensionless
* gamma — per unit of underlying price
* vega — per 1.00 volatility fraction (matching the Day-9
  ``GreeksObservation`` convention "per 1.00 vol move per unit")
* theta — per year (annualized; matching "annualized per unit")
* rho — per 1.00 rate unit (continuously compounded)

Determinism / purity
--------------------
* ``T`` comes ONLY from the Day-14 ACT/365 ``time_to_expiry()`` — this module
  never reads the wall clock, environment, DB, HTTP or broker SDKs.
* Same inputs + same ``CalculationContext`` ⇒ identical results.
* Broker Greeks remain ``GreeksObservation(source=\"BROKER\")`` upstream; model
  Greeks from this engine are separate (``calculation_id`` + versions) and
  never overwrite broker values.

Degenerate conventions (documented + tested)
--------------------------------------------
* ``T == 0`` (terminal): SUCCESS with the step convention — call delta 1/0 by
  S vs K (equality ⇒ 0), put delta −1/0 by S vs K, gamma/vega/theta/rho = 0.
  No normal-distribution formula is evaluated at T = 0.
* ``σ == 0``, T > 0 (zero-volatility): SUCCESS with the forward-comparison
  convention — ``fwd = S·e^((r−q)T)``; delta 1/0 (call) or −1/0 (put) by fwd
  vs K; gamma/vega/theta/rho = 0.
* Invalid inputs (non-positive/non-finite spot or strike, T < 0, σ < 0,
  non-finite r/q) raise ``ValueError`` from the pure function; the engine
  surfaces them as structured ``INVALID_INPUT`` ``QuantResult`` entries —
  never NaN/Infinity, never a fabricated value.
"""

from __future__ import annotations

import math
from typing import Mapping

from app.market_data.contracts import ContractVersion, Side
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    OptionMarketData,
    QuantIssue,
    QuantResult,
    time_to_expiry,
)

# ---------------------------------------------------------------------------
# Model / version identity
# ---------------------------------------------------------------------------

#: Canonical model name for this engine's outputs.
BLACK_SCHOLES_MERTON_EUROPEAN = "BLACK_SCHOLES_MERTON_EUROPEAN"
#: Model version — bump ONLY when the mathematical model changes.
MODEL_VERSION = "1.0.0"
#: Calculation id used for boundary routing.
CALCULATION_ID = "greeks.black_scholes_european"
#: Calculation implementation version.
CALCULATION_VERSION = "1.0.0"

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)

_MSG_MISSING_VOLATILITY = (
    "Model Greeks require an implied volatility input; none was supplied."
)
_MSG_INVALID_INPUT = "Invalid Greeks input: {reason}"
_MSG_NON_FINITE_OUTPUT = (
    "The calculation produced a non-finite value for these inputs."
)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _check_finite(value, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def black_scholes_merton_greeks(
    *,
    option_type: Side,
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> dict[str, float]:
    """Pure BS-Merton per-unit Greeks evaluation.

    Returns ``{delta, gamma, theta, vega, rho}`` in the documented units.
    Raises ``ValueError`` (safe, static messages) for invalid inputs; the
    engine converts those into structured ``INVALID_INPUT`` results.

    Degenerate-but-valid inputs (``time_to_expiry == 0``, ``volatility == 0``)
    return the documented deterministic conventions — never NaN/Infinity.
    """
    if not isinstance(option_type, Side) or option_type not in (Side.CALL, Side.PUT):
        raise ValueError("option_type must be Side.CALL or Side.PUT")
    S = _check_finite(spot, "spot")
    K = _check_finite(strike, "strike")
    T = _check_finite(time_to_expiry, "time_to_expiry")
    sigma = _check_finite(volatility, "volatility")
    r = _check_finite(risk_free_rate, "risk_free_rate")
    q = _check_finite(dividend_yield, "dividend_yield")

    if S <= 0:
        raise ValueError("spot must be positive")
    if K <= 0:
        raise ValueError("strike must be positive")
    if T < 0:
        raise ValueError("time_to_expiry must be non-negative")
    if sigma < 0:
        raise ValueError("volatility must be non-negative")

    is_call = option_type is Side.CALL

    # ---- Terminal convention: T == 0 -------------------------------------
    if T == 0:
        if is_call:
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    # ---- Zero-volatility convention: sigma == 0 --------------------------
    if sigma == 0:
        fwd = S * math.exp((r - q) * T)
        if is_call:
            delta = 1.0 if fwd > K else 0.0
        else:
            delta = -1.0 if fwd < K else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    # ---- General case ------------------------------------------------------
    sqrt_t = math.sqrt(T)
    vol_sqrt_t = sigma * sqrt_t
    if vol_sqrt_t == 0 or not math.isfinite(vol_sqrt_t):
        raise ValueError(
            "sigma*sqrt(T) is too small or not finite for a stable calculation"
        )
    d1 = (math.log(S) - math.log(K) + (r - q + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    pdf = _norm_pdf(d1)
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    n_d1 = _norm_cdf(d1)

    if is_call:
        delta = df_q * n_d1
    else:
        delta = df_q * (n_d1 - 1.0)
    gamma = (df_q * pdf) / (S * vol_sqrt_t)
    vega = S * df_q * pdf * sqrt_t

    if is_call:
        theta = (
            -(S * df_q * pdf * sigma) / (2.0 * sqrt_t)
            - r * K * df_r * _norm_cdf(d2)
            + q * S * df_q * n_d1
        )
        rho = K * T * df_r * _norm_cdf(d2)
    else:
        theta = (
            -(S * df_q * pdf * sigma) / (2.0 * sqrt_t)
            + r * K * df_r * _norm_cdf(-d2)
            - q * S * df_q * _norm_cdf(-d1)
        )
        rho = -K * T * df_r * _norm_cdf(-d2)

    values = {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}
    for name, value in values.items():
        if not math.isfinite(value):
            raise ValueError(f"calculated {name} is not finite for these inputs")
    return values


class BlackScholesEuropeanGreeksEngine:
    """Deterministic BS-Merton Greeks engine (Day 15).

    Implements the Day-14 :class:`~app.quant.boundary.QuantEngine` protocol:
    pure ``calculate(OptionMarketData, CalculationContext) -> QuantResult``.
    """

    calculation_id = CALCULATION_ID
    model = BLACK_SCHOLES_MERTON_EUROPEAN
    model_version = MODEL_VERSION
    calculation_version = CALCULATION_VERSION

    def calculate(
        self,
        market_data: OptionMarketData,
        context: CalculationContext,
    ) -> QuantResult:
        """Evaluate model Greeks for one option market input."""
        # The boundary already guarantees provenance + quality gates and the
        # OptionMarketData/CalculationContext validation.  Engine-level checks:
        if market_data.implied_volatility is None:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.UNAVAILABLE,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.MISSING_REQUIRED_INPUT,
                        message=_MSG_MISSING_VOLATILITY,
                        field="implied_volatility",
                    ),
                ),
            )

        t_years = time_to_expiry(
            market_data.instrument.expiry, context.reference_timestamp
        )
        try:
            values: Mapping[str, float] = black_scholes_merton_greeks(
                option_type=market_data.instrument.option_type,
                spot=market_data.spot,
                strike=market_data.instrument.strike,
                time_to_expiry=t_years,
                volatility=float(market_data.implied_volatility),
                risk_free_rate=context.risk_free_rate,
                dividend_yield=context.dividend_yield if context.dividend_yield is not None else 0.0,
            )
        except ValueError as exc:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.INVALID_INPUT,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.INVALID_INPUT_VALUE,
                        message=_MSG_INVALID_INPUT.format(reason=str(exc)),
                    ),
                ),
            )

        return self._result(
            market_data=market_data,
            context=context,
            status=CalculationStatus.SUCCESS,
            values=values,
        )

    # ------------------------------------------------------------------
    # Envelope assembly
    # ------------------------------------------------------------------

    def _result(
        self,
        *,
        market_data: OptionMarketData,
        context: CalculationContext,
        status: CalculationStatus,
        values: Mapping[str, float] | None = None,
        issues: tuple[QuantIssue, ...] = (),
    ) -> QuantResult:
        return QuantResult(
            calculation_id=self.calculation_id,
            status=status,
            values=values,
            issues=issues,
            input_quality=market_data.quality,
            provenance=market_data.provenance,
            reference_timestamp=context.reference_timestamp,
            model_version=self.model_version,
            calculation_version=self.calculation_version,
            contract_version=ContractVersion.v1_0_0.value,
        )
