"""Black-Scholes-Merton pricing engine (Day 16).

The second real quantitative engine on the Day-14 boundary: deterministic,
broker-neutral European option pricing registered through
:class:`QuantitativeEngineBoundary`, using the SAME model family and
mathematical conventions as the Day-15 Greeks engine.

    Canonical option inputs (OptionMarketData + CalculationContext)
        → QuantitativeEngineBoundary (provenance / quality guards)
        → BlackScholesMertonPricingEngine
        → QuantResult {price}          (per-unit)

Mathematical model
------------------
European Black-Scholes-Merton with a continuous dividend yield ``q`` — the
exact formulation family already verified in Day 15
(``app.quant.greeks``) and in the legacy Phase-7.19B math.  ``T`` in years,
``r``/``q``/``sigma`` as decimal fractions::

    d1 = (ln S − ln K + (r − q + σ²/2)·T) / (σ·√T)
    d2 = d1 − σ·√T
    dfQ = e^(−qT);  dfR = e^(−rT);  N = normal CDF via math.erf
    Call = S·dfQ·N(d1) − K·dfR·N(d2)
    Put  = K·dfR·N(−d2) − S·dfQ·N(−d1)

Degenerate conventions (documented + tested)
--------------------------------------------
* ``T == 0`` (terminal): SUCCESS with intrinsic value — ``max(S−K, 0)`` for a
  call, ``max(K−S, 0)`` for a put.  No normal-distribution formula is
  evaluated at T = 0.
* ``σ == 0``, T > 0 (zero-volatility): SUCCESS with the deterministic
  forward-value convention — the exact σ→0 limit of the model:
  ``Call = max(S·e^(−qT) − K·e^(−rT), 0)``,
  ``Put  = max(K·e^(−rT) − S·e^(−qT), 0)``.  Never a division by zero.
* Invalid inputs (non-positive/non-finite spot, strike or volatility,
  T < 0, non-finite r/q) raise ``ValueError`` from the pure function; the
  engine surfaces them as structured ``INVALID_INPUT`` ``QuantResult``
  entries — never NaN/Infinity, never a fabricated value.

Units
-----
* price — per-unit option premium (never scaled by lot size).

Determinism / purity
--------------------
* ``T`` comes ONLY from the Day-14 ACT/365 ``time_to_expiry()`` — this module
  never reads the wall clock, environment, DB, HTTP or broker SDKs.
* Same inputs + same ``CalculationContext`` ⇒ identical result.
* Model prices never overwrite broker-provided observations.
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
from app.quant.greeks import BLACK_SCHOLES_MERTON_EUROPEAN

# ---------------------------------------------------------------------------
# Model / version identity
# ---------------------------------------------------------------------------

#: Model version — bump ONLY when the mathematical model changes.
MODEL_VERSION = "1.0.0"
#: Calculation id used for boundary routing.
CALCULATION_ID = "pricing.black_scholes_european"
#: Calculation implementation version.
CALCULATION_VERSION = "1.0.0"

_SQRT2 = math.sqrt(2.0)

_MSG_MISSING_VOLATILITY = (
    "Model pricing requires an implied volatility input; none was supplied."
)
_MSG_INVALID_INPUT = "Invalid pricing input: {reason}"
_MSG_NON_FINITE_OUTPUT = "The calculation produced a non-finite value for these inputs."


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (Day-15 convention)."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _check_finite(value, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def black_scholes_merton_price(
    *,
    option_type: Side,
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> float:
    """Pure BS-Merton per-unit European option price.

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
        return max(S - K, 0.0) if is_call else max(K - S, 0.0)

    # ---- Zero-volatility convention: sigma == 0 --------------------------
    # The exact σ→0 limit of the model — never a division by zero.
    if sigma == 0:
        if is_call:
            return max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
        return max(K * math.exp(-r * T) - S * math.exp(-q * T), 0.0)

    # ---- General case ------------------------------------------------------
    sqrt_t = math.sqrt(T)
    vol_sqrt_t = sigma * sqrt_t
    d1 = (math.log(S) - math.log(K) + (r - q + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    if is_call:
        price = S * df_q * _norm_cdf(d1) - K * df_r * _norm_cdf(d2)
    else:
        price = K * df_r * _norm_cdf(-d2) - S * df_q * _norm_cdf(-d1)
    if not math.isfinite(price):
        raise ValueError(_MSG_NON_FINITE_OUTPUT)
    return price


class BlackScholesMertonPricingEngine:
    """Deterministic BS-Merton pricing engine (Day 16).

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
        """Evaluate the model price for one option market input."""
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
            price = black_scholes_merton_price(
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
            values={"price": price},
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
