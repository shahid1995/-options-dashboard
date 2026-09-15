"""Scenario & Time Analysis + Portfolio Sensitivity foundation (Day 18).

A deterministic, broker-neutral scenario layer on top of the Day-14 boundary
that REUSES the authoritative Day-15/16 engines through their public pure
functions — no duplicated Black-Scholes, IV or Greek mathematics.

    Explicit scenario coordinates (spot, T, sigma) over an OptionLeg
        → scenario_value        (Day-16 black_scholes_merton_price, reused)
        → model Greeks          (Day-15 black_scholes_merton_greeks, reused)
        → exposure-scaled position P/L and sensitivities
        → QuantResult           (quality + provenance + versions preserved)
    Price × Time × IV grids and portfolio aggregation are deterministic.

Determinism
-----------
* Every environmental value is explicit: scenario spot, scenario
  time-to-expiry (years; never wall-clock), scenario IV (decimal fraction),
  context rate/dividend.  The module never reads the clock, environment, DB,
  HTTP or broker SDKs (Day-14 AST guards extend over this module).
* Scenario T < 0 is invalid.  T = 0 evaluates the Day-16 intrinsic
  convention (call max(S−K,0), put max(K−S,0)) and the Day-15 step
  convention for Greeks — no normal-CDF evaluation at T = 0.
* Grid ordering is canonical and deterministic: lexicographic (spot, time,
  iv) with iv varying fastest.

P/L semantics
-------------
* ``scenario_value`` is the per-unit **model** value — never a broker
  execution price; broker truth remains authoritative for actual execution.
* Position P/L = direction_sign × (scenario_value − entry_price) × quantity.
  ``entry_price`` is explicit (per-unit); P/L is simply omitted when no entry
  price is supplied.  Direction is explicit (LONG +1 / SHORT −1); quantity is
  in contracts and may be zero (valid — zero exposure).  No one is assumed
  to be long.
* Exposure-scaled sensitivities = model greek × direction × quantity
  (Day-15 conventions: theta annualized, vega per 1.00 vol fraction).  These
  are MODEL sensitivities — never claims about broker Greeks.

Quality / provenance
--------------------
* Quality (Day-12 state) and provenance are consumed — never recomputed
  (AST-enforced).  INSUFFICIENT quality or missing provenance yield the
  Day-14 structured UNAVAILABLE semantics; missing/invalid inputs map to
  UNAVAILABLE/MISSING_REQUIRED_INPUT and INVALID_INPUT respectively.  No
  NaN/Infinity, no silent coercion, no fabricated values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Sequence

from app.market_data.contracts import ContractVersion, Provenance, QualityState, Side
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    QuantIssue,
    QuantResult,
)
from app.quant.greeks import BLACK_SCHOLES_MERTON_EUROPEAN, black_scholes_merton_greeks
from app.quant.pricing import black_scholes_merton_price

# ---------------------------------------------------------------------------
# Model / version identity
# ---------------------------------------------------------------------------

#: Canonical scenario-analysis model label for this module's envelopes.
MODEL_NAME = "SCENARIO_ANALYSIS"
#: The model family whose math is reused (identical to Days 15/16).
GREEKS_MODEL_FAMILY = BLACK_SCHOLES_MERTON_EUROPEAN
#: Model version — bump ONLY when the evaluation semantics change.
MODEL_VERSION = "1.0.0"
#: Calculation id used in result envelopes.
CALCULATION_ID = "scenario.option_leg_v1"
#: Calculation implementation version.
CALCULATION_VERSION = "1.0.0"

_MSG_MISSING_PROVENANCE = (
    "The leg carries no provenance — its inputs cannot be attributed and the "
    "scenario evaluation is unavailable."
)
_MSG_INSUFFICIENT_QUALITY = (
    "The leg's input quality is INSUFFICIENT — required inputs are unreliable "
    "and the scenario evaluation is unavailable."
)
_MSG_MISSING_IV = (
    "No implied volatility is available for this leg and none was supplied "
    "for the scenario — missing is not zero."
)
_MSG_INVALID_INPUT = "Invalid scenario input: {reason}"


# ---------------------------------------------------------------------------
# Position direction
# ---------------------------------------------------------------------------


class PositionDirection(str, Enum):
    """Explicit position direction — no implicit assumption that users are long."""

    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> int:
        return 1 if self is PositionDirection.LONG else -1


# ---------------------------------------------------------------------------
# Scenario contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionLeg:
    """Pure-data option position leg (no DB, no persistence, no execution).

    * ``option_type`` — Side.CALL / Side.PUT.
    * ``strike`` — positive finite strike.
    * ``expiry`` — ISO YYYY-MM-DD contract expiry (identity/validation; the
      scenario time axis supplies explicit time-to-expiry values).
    * ``quantity`` — contracts (zero valid); never negative.
    * ``direction`` — LONG (+1) / SHORT (−1), explicit.
    * ``entry_price`` — per-unit reference for P/L; ``None`` = no P/L basis
      (P/L is then omitted, never fabricated).
    * ``implied_volatility`` — the leg's explicit current/base IV (decimal);
      scenario evaluation defaults to it when no scenario IV is supplied.
    * ``quality`` / ``provenance`` — Day-12/Day-9 state consumed, never
      recomputed.
    """

    option_type: Side
    strike: float
    expiry: str
    quantity: float = 1.0
    direction: PositionDirection = PositionDirection.LONG
    entry_price: float | None = None
    implied_volatility: float | None = None
    quality: QualityState | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.option_type, Side) or self.option_type not in (
            Side.CALL,
            Side.PUT,
        ):
            raise ValueError("option_type must be Side.CALL or Side.PUT")
        if not isinstance(self.strike, (int, float)) or not math.isfinite(self.strike):
            raise ValueError("strike must be a finite number")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        try:
            datetime.strptime(self.expiry, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"expiry must be an ISO YYYY-MM-DD date, got {self.expiry!r}"
            ) from exc
        if not isinstance(self.quantity, (int, float)) or not math.isfinite(self.quantity):
            raise ValueError("quantity must be a finite number")
        if self.quantity < 0:
            raise ValueError("quantity must be non-negative")
        if not isinstance(self.direction, PositionDirection):
            raise ValueError("direction must be PositionDirection.LONG or SHORT")
        if self.entry_price is not None and (
            not isinstance(self.entry_price, (int, float))
            or not math.isfinite(self.entry_price)
        ):
            raise ValueError("entry_price must be a finite number or None")
        if self.implied_volatility is not None and (
            not isinstance(self.implied_volatility, (int, float))
            or not math.isfinite(self.implied_volatility)
        ):
            raise ValueError("implied_volatility must be a finite number or None")
        if self.implied_volatility is not None and self.implied_volatility < 0:
            raise ValueError("implied_volatility must be non-negative")
        if self.quality is not None and not isinstance(self.quality, QualityState):
            raise ValueError("quality must be a QualityState or None")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")


@dataclass(frozen=True)
class ScenarioPoint:
    """One explicit scenario coordinate: spot, time-to-expiry (years), IV."""

    spot: float
    time_to_expiry: float
    implied_volatility: float


@dataclass(frozen=True)
class ScenarioGrid:
    """Deterministic Price × Time × IV coordinate grid.

    Canonical ordering: lexicographic ``(spot, time, iv)`` with ``iv`` varying
    fastest — ``for spot in spots: for t in times: for iv in ivs``.
    ``len(points()) == n_spots × n_times × n_ivs``.
    """

    spots: tuple[float, ...] = ()
    times: tuple[float, ...] = ()
    ivs: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        for name, values in (
            ("spots", self.spots),
            ("times", self.times),
            ("ivs", self.ivs),
        ):
            for value in values:
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{name} entries must be finite numbers")
        for value in self.spots:
            if value <= 0:
                raise ValueError("scenario spots must be positive")
        for value in self.times:
            if value < 0:
                raise ValueError("scenario times must be non-negative")
        for value in self.ivs:
            if value < 0:
                raise ValueError("scenario ivs must be non-negative")

    def points(self) -> tuple[ScenarioPoint, ...]:
        return tuple(
            ScenarioPoint(spot=spot, time_to_expiry=t, implied_volatility=iv)
            for spot in self.spots
            for t in self.times
            for iv in self.ivs
        )


# ---------------------------------------------------------------------------
# Pure scenario value (documented reuse of the Day-16 engine)
# ---------------------------------------------------------------------------


def scenario_value(
    *,
    option_type: Side,
    spot: float,
    strike: float,
    time_to_expiry: float,
    implied_volatility: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
) -> float:
    """Per-unit model value under explicit scenario inputs.

    Thin documented wrapper over the Day-16
    ``black_scholes_merton_price`` (the authoritative pricing engine) — no
    formula duplication.  Raises ``ValueError`` (safe, static messages) for
    invalid inputs; T = 0 returns the Day-16 intrinsic convention.
    """
    return black_scholes_merton_price(
        option_type=option_type,
        spot=spot,
        strike=strike,
        time_to_expiry=time_to_expiry,
        volatility=implied_volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )


# ---------------------------------------------------------------------------
# Per-leg scenario evaluation
# ---------------------------------------------------------------------------


def evaluate_leg(
    leg: OptionLeg,
    context: CalculationContext,
    *,
    spot: float,
    time_to_expiry: float,
    implied_volatility: float | None = None,
) -> QuantResult:
    """Evaluate one option leg under ONE explicit scenario coordinate.

    Returns a Day-14 :class:`QuantResult` (the envelope is reused — no second
    result type).  Values: ``scenario_value`` (per unit), exposure-scaled
    ``delta/gamma/theta/vega`` (= model greek × direction × quantity), the
    scenario coordinates, and — only when the leg has an ``entry_price`` —
    ``pnl`` = direction_sign × (scenario_value − entry_price) × quantity.
    """
    if not isinstance(leg, OptionLeg):
        raise TypeError("leg must be an OptionLeg")
    if not isinstance(context, CalculationContext):
        raise TypeError("context must be a CalculationContext")

    # Quality / provenance gates mirror the Day-14 boundary semantics.
    if leg.provenance is None:
        return _result(
            leg=leg,
            context=context,
            status=CalculationStatus.UNAVAILABLE,
            issues=(
                QuantIssue(
                    code=CalculationIssueCode.MISSING_PROVENANCE,
                    message=_MSG_MISSING_PROVENANCE,
                    field="provenance",
                ),
            ),
        )
    if leg.quality is QualityState.INSUFFICIENT:
        return _result(
            leg=leg,
            context=context,
            status=CalculationStatus.UNAVAILABLE,
            issues=(
                QuantIssue(
                    code=CalculationIssueCode.INSUFFICIENT_QUALITY,
                    message=_MSG_INSUFFICIENT_QUALITY,
                    field="quality",
                ),
            ),
        )

    iv = implied_volatility if implied_volatility is not None else leg.implied_volatility
    if iv is None:
        return _result(
            leg=leg,
            context=context,
            status=CalculationStatus.UNAVAILABLE,
            issues=(
                QuantIssue(
                    code=CalculationIssueCode.MISSING_REQUIRED_INPUT,
                    message=_MSG_MISSING_IV,
                    field="implied_volatility",
                ),
            ),
        )

    try:
        value = scenario_value(
            option_type=leg.option_type,
            spot=spot,
            strike=leg.strike,
            time_to_expiry=time_to_expiry,
            implied_volatility=iv,
            risk_free_rate=context.risk_free_rate,
            dividend_yield=context.dividend_yield if context.dividend_yield is not None else 0.0,
        )
        greeks = black_scholes_merton_greeks(
            option_type=leg.option_type,
            spot=spot,
            strike=leg.strike,
            time_to_expiry=time_to_expiry,
            volatility=iv,
            risk_free_rate=context.risk_free_rate,
            dividend_yield=context.dividend_yield if context.dividend_yield is not None else 0.0,
        )
    except ValueError as exc:
        return _result(
            leg=leg,
            context=context,
            status=CalculationStatus.INVALID_INPUT,
            issues=(
                QuantIssue(
                    code=CalculationIssueCode.INVALID_INPUT_VALUE,
                    message=_MSG_INVALID_INPUT.format(reason=str(exc)),
                ),
            ),
        )

    scale = leg.direction.sign * leg.quantity
    values: dict[str, float] = {
        "scenario_value": value,
        "delta": greeks["delta"] * scale,
        "gamma": greeks["gamma"] * scale,
        "theta": greeks["theta"] * scale,
        "vega": greeks["vega"] * scale,
        "spot": float(spot),
        "time_to_expiry": float(time_to_expiry),
        "implied_volatility": float(iv),
    }
    if leg.entry_price is not None:
        values["entry_price"] = float(leg.entry_price)
        values["pnl"] = leg.direction.sign * (value - leg.entry_price) * leg.quantity

    return _result(
        leg=leg,
        context=context,
        status=CalculationStatus.SUCCESS,
        values=values,
    )


def evaluate_leg_grid(
    leg: OptionLeg,
    context: CalculationContext,
    grid: ScenarioGrid,
) -> tuple[tuple[ScenarioPoint, QuantResult], ...]:
    """Evaluate one leg across every grid point in the canonical order.

    Deterministic: identical ``(leg, context, grid)`` ⇒ identical output
    sequence.
    """
    if not isinstance(grid, ScenarioGrid):
        raise TypeError("grid must be a ScenarioGrid")
    return tuple(
        (point, evaluate_leg(leg, context, spot=point.spot,
                             time_to_expiry=point.time_to_expiry,
                             implied_volatility=point.implied_volatility))
        for point in grid.points()
    )


# ---------------------------------------------------------------------------
# Portfolio sensitivity foundation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioScenarioResult:
    """Aggregated scenario result across pure-data option legs.

    * ``leg_results`` — per-leg :class:`QuantResult` envelopes.
    * ``delta/gamma/theta/vega`` — Σ exposure-scaled MODEL sensitivities over
      successfully priced legs (``None`` when no leg priced).  These are model
      sensitivities, never claims about broker Greeks.
    * ``total_pnl`` — Σ per-leg P/L where an entry price exists (``None`` when
      no priced leg carries one).
    * ``partial`` — True when any leg did not price; ``unavailable_reasons``
      lists the structured reasons.  A partial total is never presented as a
      complete calculation.
    """

    spot: float
    time_to_expiry: float
    leg_results: tuple[QuantResult, ...]
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    total_pnl: float | None
    partial: bool
    unavailable_reasons: tuple[QuantIssue, ...] = ()


def evaluate_portfolio(
    legs: Sequence[OptionLeg],
    context: CalculationContext,
    *,
    spot: float,
    time_to_expiry: float,
    implied_volatility: float | None = None,
) -> PortfolioScenarioResult:
    """Evaluate a portfolio of legs under one scenario coordinate.

    Portfolio inputs are pure data — no database, no persistence, no
    execution behavior.  When ``implied_volatility`` is ``None`` each leg is
    priced with its own explicit leg IV (never silently derived elsewhere).
    """
    if not isinstance(legs, Sequence):
        raise TypeError("legs must be a sequence of OptionLeg")

    leg_results: list[QuantResult] = []
    for leg in legs:
        if not isinstance(leg, OptionLeg):
            raise TypeError("every portfolio leg must be an OptionLeg")
        leg_results.append(
            evaluate_leg(
                leg,
                context,
                spot=spot,
                time_to_expiry=time_to_expiry,
                implied_volatility=implied_volatility,
            )
        )

    priced = [r for r in leg_results if r.status is CalculationStatus.SUCCESS]
    partial = len(priced) != len(leg_results)
    reasons = tuple(
        issue
        for r in leg_results
        if r.status is not CalculationStatus.SUCCESS
        for issue in r.issues
    )

    if not priced:
        return PortfolioScenarioResult(
            spot=float(spot),
            time_to_expiry=float(time_to_expiry),
            leg_results=tuple(leg_results),
            delta=None,
            gamma=None,
            theta=None,
            vega=None,
            total_pnl=None,
            partial=partial,
            unavailable_reasons=reasons,
        )

    def _sum(key: str) -> float:
        return sum(r.values[key] for r in priced if r.values is not None and key in r.values)

    pnl_legs = [r for r in priced if r.values is not None and "pnl" in r.values]
    total_pnl = _sum("pnl") if pnl_legs else None

    return PortfolioScenarioResult(
        spot=float(spot),
        time_to_expiry=float(time_to_expiry),
        leg_results=tuple(leg_results),
        delta=_sum("delta"),
        gamma=_sum("gamma"),
        theta=_sum("theta"),
        vega=_sum("vega"),
        total_pnl=total_pnl,
        partial=partial,
        unavailable_reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Envelope assembly (reuses the Day-14 QuantResult)
# ---------------------------------------------------------------------------


def _result(
    *,
    leg: OptionLeg,
    context: CalculationContext,
    status: CalculationStatus,
    values: Mapping[str, float] | None = None,
    issues: tuple[QuantIssue, ...] = (),
) -> QuantResult:
    return QuantResult(
        calculation_id=CALCULATION_ID,
        status=status,
        values=values,
        issues=issues,
        input_quality=leg.quality,
        provenance=leg.provenance,
        reference_timestamp=context.reference_timestamp,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
        contract_version=ContractVersion.v1_0_0.value,
    )
