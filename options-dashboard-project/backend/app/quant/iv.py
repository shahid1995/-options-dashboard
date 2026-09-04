"""Implied Volatility solver + engine (Day 16).

The third real quantitative engine on the Day-14 boundary: a deterministic,
broker-neutral bounded root solver that inverts the Day-16 BS-Merton pricing
model for the volatility implied by an observed market price.

    Canonical option inputs + observed market price
        → QuantitativeEngineBoundary (provenance / quality guards)
        → BlackScholesMertonImpliedVolatilityEngine
        → QuantResult {implied_volatility}   (decimal fraction: 0.1824 = 18.24%)

Solver
------
Bounded **Brent** root solve (pure stdlib — no SciPy/NumPy; the repository has
no third-party numerical dependencies) on ``g(σ) = price(σ) − market_price``
over the documented bracket ``[VOLATILITY_MIN, VOLATILITY_MAX] = [0.0, 10.0]``.
Because the BS-Merton price is strictly monotone increasing in σ for T > 0
(vega > 0) and the σ = 0 degenerate price equals the theoretical lower bound
exactly, a sign change always exists inside the bracket whenever the market
price lies strictly between the theoretical lower bound and the σ = 10 model
price — so the failure taxonomy below is exhaustive and deterministic.

Theoretical bounds (per the Day-16 plan):
    Call lower = max(S·e^(−qT) − K·e^(−rT), 0)   Call upper = S·e^(−qT)
    Put  lower = max(K·e^(−rT) − S·e^(−qT), 0)   Put  upper = K·e^(−rT)

Convergence policy (explicit, documented, tested)
    price_tolerance   — |price(σ) − market| ≤ 1e-9 × max(1, market)
    sigma_tolerance   — bracket width ≤ 1e-10 × max(1, σ)
    max_iterations    — 100
    volatility domain — [0.0, 10.0] (0% → 1000%)

Failure taxonomy → boundary semantics
    EXPIRED (T == 0)                → UNAVAILABLE / issue EXPIRED
    BELOW_LOWER_BOUND               → INVALID_INPUT / BELOW_LOWER_BOUND
    ABOVE_THEORETICAL_MAX           → INVALID_INPUT / ABOVE_THEORETICAL_MAX
    NO_BRACKET (price in the band   → FAILED / NO_BRACKET
      (price(10), theoretical max])
    CONVERGENCE_FAILED              → FAILED / CONVERGENCE_FAILED
    market == lower bound (± tol)   → SUCCESS with σ = 0.0 (the exact
      zero-volatility inverse of the model — never a fabricated value)

Determinism / purity
--------------------
* Solver and engine never read the wall clock, environment, DB, HTTP or
  broker SDKs; time enters only through the explicit ACT/365 T derived from
  ``OptionMarketData.instrument.expiry`` + ``CalculationContext``.
* IV is returned as a decimal volatility fraction — never percentage points.
* Model IV never overwrites broker-provided IV observations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
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
from app.quant.pricing import black_scholes_merton_price

# ---------------------------------------------------------------------------
# Model / version identity
# ---------------------------------------------------------------------------

#: Model version — bump ONLY when the mathematical model changes.
MODEL_VERSION = "1.0.0"
#: Calculation id used for boundary routing.
CALCULATION_ID = "implied_volatility.black_scholes_european"
#: Calculation implementation version.
CALCULATION_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Solver parameters (explicit + documented)
# ---------------------------------------------------------------------------

#: Solver domain lower bound (σ = 0 is the degenerate zero-volatility model).
VOLATILITY_MIN = 0.0
#: Solver domain upper bound — 10.0 = 1000% annualized volatility.
VOLATILITY_MAX = 10.0
#: Price residual tolerance (relative to max(1, market_price)).
PRICE_TOLERANCE = 1e-9
#: Volatility bracket-width tolerance (relative to max(1, σ)).
SIGMA_TOLERANCE = 1e-10
#: Maximum Brent iterations.
MAX_ITERATIONS = 100
#: Relative tolerance for the theoretical price-bound gates (forgives
#: floating-point noise only — never accepts a genuinely infeasible quote).
BOUND_TOLERANCE_RELATIVE = 1e-8

_EPS = 2.220446049250313e-16

_MSG_MISSING_PRICE = (
    "Implied volatility requires an observed market price; none was supplied."
)
_MSG_INVALID_INPUT = "Invalid implied-volatility input: {reason}"
_MSG_EXPIRED = (
    "The contract is at/after expiry — implied volatility is undefined because "
    "the model price is intrinsic for any volatility."
)
_MSG_BELOW = (
    "The observed market price is below the option's theoretical lower bound — "
    "no volatility solves the model for this quote."
)
_MSG_ABOVE = (
    "The observed market price exceeds the option's theoretical maximum — no "
    "volatility solves the model for this quote."
)
_MSG_NO_BRACKET = (
    "The observed price lies above the model price at the solver's maximum "
    "volatility (10.0) — no root exists in the documented volatility domain."
)
_MSG_CONVERGENCE = (
    "The bounded root solver exhausted its iteration budget without converging."
)


# ---------------------------------------------------------------------------
# Solver outcomes
# ---------------------------------------------------------------------------


class IvSolverOutcome(str, Enum):
    """Deterministic outcomes of the pure implied-volatility solve."""

    SUCCESS = "SUCCESS"
    EXPIRED = "EXPIRED"
    BELOW_LOWER_BOUND = "BELOW_LOWER_BOUND"
    ABOVE_THEORETICAL_MAX = "ABOVE_THEORETICAL_MAX"
    NO_BRACKET = "NO_BRACKET"
    CONVERGENCE_FAILED = "CONVERGENCE_FAILED"


@dataclass(frozen=True)
class VolatilitySolve:
    """Pure-solver result: the volatility and its outcome.

    ``sigma`` is the decimal volatility fraction and is ``None`` unless the
    outcome is :attr:`IvSolverOutcome.SUCCESS`.
    """

    sigma: float | None
    outcome: IvSolverOutcome


# ---------------------------------------------------------------------------
# Bounded Brent root finder (pure stdlib, deterministic)
# ---------------------------------------------------------------------------


def _brent(
    f,
    xa: float,
    xb: float,
    xtol: float,
    ftol: float,
    fscale: float,
    max_iterations: int,
) -> tuple[float, bool]:
    """Brent root finder on ``[xa, xb]`` (assumes a sign change).

    Returns ``(root, converged)``.  Convergence means the bracket width fell
    below ``xtol × max(1, |x|)`` (machine-epsilon floored) or the residual
    fell below ``ftol × fscale``.  Exhausting ``max_iterations`` without
    meeting either tolerance returns ``converged=False``.
    """
    fa = f(xa)
    fb = f(xb)
    if fa == 0.0:
        return (xa, True)
    if fb == 0.0:
        return (xb, True)
    if fa * fb > 0.0:
        return ((xa + xb) / 2.0, False)

    c, fc = xa, fa
    d = e = xb - xa
    for _ in range(max_iterations):
        if fb * fc > 0.0:
            c, fc = xa, fa
            d = e = xb - xa
        if abs(fc) < abs(fb):
            xa, xb, c = xb, c, xb
            fa, fb, fc = fb, fc, fb
        tol1 = 2.0 * _EPS * abs(xb) + 0.5 * xtol
        xm = 0.5 * (c - xb)
        if abs(xm) <= tol1 or abs(fb) <= ftol * fscale:
            return (xb, True)
        if abs(e) >= tol1 and abs(fa) > abs(fb):
            s = fb / fa
            if xa == c:
                p = 2.0 * xm * s
                q = 1.0 - s
            else:
                q = fa / fc
                r = fb / fc
                p = s * (2.0 * xm * q * (q - r) - (xb - xa) * (r - 1.0))
                q = (q - 1.0) * (r - 1.0) * (s - 1.0)
            if p > 0.0:
                q = -q
            p = abs(p)
            min1 = 3.0 * xm * q - abs(tol1 * q)
            min2 = abs(e * q)
            if 2.0 * p < (min1 if min1 < min2 else min2):
                e = d
                d = p / q
            else:
                d = xm
                e = d
        else:
            d = xm
            e = d
        xa = xb
        fa = fb
        if abs(d) > tol1:
            xb += d
        else:
            xb += abs(tol1) if xm > 0 else -abs(tol1)
        fb = f(xb)
    return (xb, False)


# ---------------------------------------------------------------------------
# Pure implied-volatility solve
# ---------------------------------------------------------------------------


def implied_volatility_solve(
    *,
    option_type: Side,
    spot: float,
    strike: float,
    time_to_expiry: float,
    market_price: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    price_tolerance: float = PRICE_TOLERANCE,
    sigma_tolerance: float = SIGMA_TOLERANCE,
    max_iterations: int = MAX_ITERATIONS,
) -> VolatilitySolve:
    """Pure BS-Merton implied-volatility solve.

    Solves ``price(σ) = market_price`` for the decimal volatility fraction σ
    over the documented domain ``[VOLATILITY_MIN, VOLATILITY_MAX]``.  Returns
    a :class:`VolatilitySolve` — the outcome taxonomy is exhaustive and
    deterministic; nothing is ever guessed.

    Raises ``ValueError`` (safe, static messages) only for structurally
    invalid scalar inputs (non-positive/non-finite spot, strike or market
    price, negative ``time_to_expiry``, non-finite r/q, bad side, invalid
    tolerance arguments).
    """
    if not isinstance(option_type, Side) or option_type not in (Side.CALL, Side.PUT):
        raise ValueError("option_type must be Side.CALL or Side.PUT")

    def _finite(value, name: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        return value

    S = _finite(spot, "spot")
    K = _finite(strike, "strike")
    T = _finite(time_to_expiry, "time_to_expiry")
    market = _finite(market_price, "market_price")
    r = _finite(risk_free_rate, "risk_free_rate")
    q = _finite(dividend_yield, "dividend_yield")
    price_tol = _finite(price_tolerance, "price_tolerance")
    sigma_tol = _finite(sigma_tolerance, "sigma_tolerance")

    if S <= 0:
        raise ValueError("spot must be positive")
    if K <= 0:
        raise ValueError("strike must be positive")
    if T < 0:
        raise ValueError("time_to_expiry must be non-negative")
    if market <= 0:
        raise ValueError("market_price must be positive")
    if price_tol < 0 or sigma_tol < 0:
        raise ValueError("price_tolerance and sigma_tolerance must be non-negative")
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
        raise ValueError("max_iterations must be an integer")
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")

    is_call = option_type is Side.CALL

    # ---- Expired: IV is undefined at/after expiry ------------------------
    if T == 0:
        return VolatilitySolve(None, IvSolverOutcome.EXPIRED)

    # ---- Theoretical bounds (see module docstring) ------------------------
    df_q = math.exp(-q * T)
    df_r = math.exp(-r * T)
    if is_call:
        lower = max(S * df_q - K * df_r, 0.0)
        upper = S * df_q
    else:
        lower = max(K * df_r - S * df_q, 0.0)
        upper = K * df_r

    bound_tol = BOUND_TOLERANCE_RELATIVE * max(1.0, upper)
    if market < lower - bound_tol:
        return VolatilitySolve(None, IvSolverOutcome.BELOW_LOWER_BOUND)
    if market > upper + bound_tol:
        return VolatilitySolve(None, IvSolverOutcome.ABOVE_THEORETICAL_MAX)
    if market <= lower:
        # Market at the forward-intrinsic lower bound (within float noise):
        # σ = 0 is the exact zero-volatility inverse of the model.
        return VolatilitySolve(0.0, IvSolverOutcome.SUCCESS)

    # ---- Root solve over [0, VOLATILITY_MAX] ------------------------------
    def _g(sigma: float) -> float:
        return black_scholes_merton_price(
            option_type=option_type,
            spot=S,
            strike=K,
            time_to_expiry=T,
            volatility=sigma,
            risk_free_rate=r,
            dividend_yield=q,
        ) - market

    f_low = _g(VOLATILITY_MIN)  # < 0 (market > lower == price(0))
    f_high = _g(VOLATILITY_MAX)
    if f_high < 0:
        # Market in the band (price(σ_max), theoretical max]: no root exists
        # in the documented volatility domain.
        return VolatilitySolve(None, IvSolverOutcome.NO_BRACKET)

    root, converged = _brent(
        _g,
        VOLATILITY_MIN,
        VOLATILITY_MAX,
        sigma_tol,
        price_tol,
        max(1.0, market),
        max_iterations,
    )
    if not converged:
        return VolatilitySolve(None, IvSolverOutcome.CONVERGENCE_FAILED)
    if root < 0.0 or not math.isfinite(root):
        return VolatilitySolve(None, IvSolverOutcome.CONVERGENCE_FAILED)
    return VolatilitySolve(root, IvSolverOutcome.SUCCESS)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class BlackScholesMertonImpliedVolatilityEngine:
    """Deterministic BS-Merton implied-volatility engine (Day 16).

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
        """Solve the implied volatility for one option market input."""
        # The boundary already guarantees provenance + quality gates and the
        # OptionMarketData/CalculationContext validation.  Engine-level checks:
        if market_data.market_price is None:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.UNAVAILABLE,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.MISSING_REQUIRED_INPUT,
                        message=_MSG_MISSING_PRICE,
                        field="market_price",
                    ),
                ),
            )

        t_years = time_to_expiry(
            market_data.instrument.expiry, context.reference_timestamp
        )
        try:
            solve = implied_volatility_solve(
                option_type=market_data.instrument.option_type,
                spot=market_data.spot,
                strike=market_data.instrument.strike,
                time_to_expiry=t_years,
                market_price=float(market_data.market_price),
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

        if solve.outcome is IvSolverOutcome.SUCCESS:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.SUCCESS,
                values={"implied_volatility": solve.sigma},
            )
        if solve.outcome is IvSolverOutcome.EXPIRED:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.UNAVAILABLE,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.EXPIRED,
                        message=_MSG_EXPIRED,
                        field="time_to_expiry",
                    ),
                ),
            )
        if solve.outcome is IvSolverOutcome.BELOW_LOWER_BOUND:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.INVALID_INPUT,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.BELOW_LOWER_BOUND,
                        message=_MSG_BELOW,
                        field="market_price",
                    ),
                ),
            )
        if solve.outcome is IvSolverOutcome.ABOVE_THEORETICAL_MAX:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.INVALID_INPUT,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.ABOVE_THEORETICAL_MAX,
                        message=_MSG_ABOVE,
                        field="market_price",
                    ),
                ),
            )
        if solve.outcome is IvSolverOutcome.NO_BRACKET:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.FAILED,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.NO_BRACKET,
                        message=_MSG_NO_BRACKET,
                        field="volatility",
                    ),
                ),
            )
        return self._result(
            market_data=market_data,
            context=context,
            status=CalculationStatus.FAILED,
            issues=(
                QuantIssue(
                    code=CalculationIssueCode.CONVERGENCE_FAILED,
                    message=_MSG_CONVERGENCE,
                    field="volatility",
                ),
            ),
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
