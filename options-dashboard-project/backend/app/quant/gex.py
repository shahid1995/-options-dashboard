"""GEX Calculation & Gamma Profile foundation (Day 17).

The fourth real quantitative engine on the Day-14 boundary: a deterministic,
broker-neutral **Gamma Exposure (GEX)** engine plus a reusable gamma-profile
aggregation layer, both registered/consuming the Day-14/15/16 quantitative
conventions.

    Canonical option inputs + gamma + OI + explicit greeks source
        → QuantitativeEngineBoundary (provenance / quality guards)
        → GexCalculationEngine
        → QuantResult {raw_gex, signed_gex}       (per option)
        → build_gamma_profile(...) → GammaProfile  (strike rows + totals)

Canonical formula (GEX_V1_0_SPEC §6, preserved exactly by the Phase-8A
``live_gex`` service and the frontend ``gex.js``)::

    Raw GEX_i = Gamma_i × OI_i × S² × 0.01

OI units
--------
**OI is in contracts — never lots.**  No lot-size multiplier is ever applied
inside this engine (spec §11 documents the evidence chain: Upstox
``market_data.oi`` passes through unconverted and represents outstanding
contracts).  If a future broker reports OI in a different unit the adapter
must normalize to contracts at the mapping boundary — not here.

Sign convention (spec §6.1) — explicit modeling convention, never a claim
about observed dealer positions::

    Call GEX = +Raw GEX        Put GEX = −Raw GEX
    positioning_model = NAIVE_DEALER_CONVENTION   call_sign = +1  put_sign = −1

Greeks source separation (Day 9 / §7)
-------------------------------------
Every GEX input identifies whether its gamma came from a broker
(``GREEKS_SOURCE_BROKER``) or the StrikeNova model
(``GREEKS_SOURCE_MODEL``).  The engine requires the label, preserves it on the
result (``QuantResult.greeks_source``), never overwrites broker gamma with
model gamma, and the profile builder **rejects** any set of rows that would
silently mix broker and model gamma.

Missing vs zero
---------------
* Missing (``None``) gamma / OI / source ⇒ UNAVAILABLE / INVALID — never a
  fabricated value (spec §10: missing data is not zero).
* Legitimately zero gamma or OI ⇒ a valid contribution of exactly 0.0 (spec
  §10 only declares NaN/infinity/non-numeric gamma and negative OI invalid).

Determinism / purity
--------------------
The engine has no time dependence and never reads the wall clock, the
environment, the DB, HTTP or broker SDKs.  Same inputs + same context ⇒
identical result; identical input rows ⇒ identical profile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.market_data.contracts import ContractVersion, QualityState, Side
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    OptionMarketData,
    QuantIssue,
    QuantResult,
)

# ---------------------------------------------------------------------------
# Model / version identity
# ---------------------------------------------------------------------------

#: Canonical model name for this engine's outputs.
MODEL = "GAMMA_EXPOSURE"
#: Model version — bump ONLY when the mathematical model changes.
MODEL_VERSION = "1.0.0"
#: Calculation id used for boundary routing.
CALCULATION_ID = "gex.naive_dealer_v1"
#: Calculation implementation version.
CALCULATION_VERSION = "1.0.0"

#: Approved methodology identifier (GEX_V1_0_SPEC / live_gex / gex.js).
METHOD_VERSION = "GEX_STANDARD_V1"
#: The declared positioning model — a modeling convention, not observed fact.
SIGN_CONVENTION = "NAIVE_DEALER_CONVENTION"
#: The 1%-move factor in the canonical GEX formula.
GEX_FACTOR = 0.01

#: Explicit sign assignments under NAIVE_DEALER_CONVENTION.
CALL_SIGN = 1
PUT_SIGN = -1

#: Gamma source vocabulary (the Day-9 GreeksObservation source tokens).
GREEKS_SOURCE_BROKER = "BROKER"
GREEKS_SOURCE_MODEL = "MODEL"
_GREEKS_SOURCES = frozenset({GREEKS_SOURCE_BROKER, GREEKS_SOURCE_MODEL})

_MSG_INVALID_INPUT = "Invalid GEX input: {reason}"
_MSG_MISSING_GAMMA = (
    "GEX requires a gamma input; none was supplied (missing is not zero)."
)
_MSG_MISSING_OI = (
    "GEX requires an open-interest input in contracts; none was supplied "
    "(missing is not zero)."
)
_MSG_MISSING_SOURCE = (
    "GEX requires an explicit greeks source (BROKER or MODEL) so broker and "
    "model gamma are never mixed; none was supplied."
)
_MSG_INVALID_SOURCE = (
    "The greeks source must be 'BROKER' or 'MODEL'; got an unknown token."
)
_MSG_MIXED_SOURCES = (
    "Gamma profile rows mix BROKER and MODEL gamma — the profile never "
    "silently mixes greeks sources."
)
_MSG_SPOT_MISMATCH = (
    "Gamma profile rows must share the same underlying spot for one profile."
)


# ---------------------------------------------------------------------------
# Pure GEX mathematics
# ---------------------------------------------------------------------------


def _finite(value, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _validated_scalars(gamma, oi, spot) -> tuple[float, float, float]:
    """Validate and coerce the three GEX scalars (raises ValueError)."""
    g = _finite(gamma, "gamma")
    o = _finite(oi, "open_interest")
    s = _finite(spot, "spot")
    if g < 0:
        raise ValueError("gamma must be non-negative")
    if o < 0:
        raise ValueError("open_interest must be non-negative")
    if s <= 0:
        raise ValueError("spot must be positive")
    return g, o, s


def raw_gex(gamma, oi: float, spot: float) -> float:
    """Pure raw GEX for one option: ``gamma × OI × spot² × 0.01``.

    OI is in **contracts** (never lots).  Raises ``ValueError`` (safe, static
    messages) for invalid inputs; the engine converts those into structured
    ``INVALID_INPUT`` results.  Zero gamma/OI are valid and yield 0.0.
    """
    g, o, s = _validated_scalars(gamma, oi, spot)
    return g * o * s * s * GEX_FACTOR


def dealer_signed_gex(option_type: Side, gamma, oi: float, spot: float) -> float:
    """Signed GEX for one option under NAIVE_DEALER_CONVENTION.

    ``Call GEX = +raw``, ``Put GEX = −raw`` (spec §6.1).  Raises
    ``ValueError`` for invalid inputs or a non-CALL/PUT side.
    """
    if not isinstance(option_type, Side) or option_type not in (Side.CALL, Side.PUT):
        raise ValueError("option_type must be Side.CALL or Side.PUT")
    raw = raw_gex(gamma, oi, spot)
    return raw if option_type is Side.CALL else -raw


# ---------------------------------------------------------------------------
# Gamma profile types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileStrikeRow:
    """One strike row of a gamma profile (sorted ascending by strike).

    A side that had no observed rows stays ``None`` (missing is not zero);
    ``net_gex`` is the signed sum of the present sides.
    """

    strike: float
    call_gex: float | None
    put_gex: float | None
    net_gex: float


@dataclass(frozen=True)
class ProfileExclusion:
    """A structured record of an input row excluded from a gamma profile.

    ``message`` is a safe static string — never a broker payload, credential,
    or exception text.
    """

    reason: CalculationIssueCode
    strike: float | None
    side: Side | None
    message: str

    def __repr__(self) -> str:
        return (
            f"ProfileExclusion(reason={self.reason.value!r}, "
            f"strike={self.strike!r}, side={self.side!r}, "
            f"message={self.message!r})"
        )


@dataclass(frozen=True)
class GammaProfile:
    """A deterministic gamma profile across strikes for one underlying spot.

    * ``rows`` — one :class:`ProfileStrikeRow` per strike with at least one
      valid side, sorted by strike ascending.
    * ``total_call_gex`` / ``total_put_gex`` — sum over present rows of that
      side; ``None`` when the profile contains no row of that side (missing
      is not zero).
    * ``total_net_gex`` — signed sum of all strike nets (``None`` for an
      empty profile).
    * ``greeks_source`` — the single explicit gamma source of the valid rows.
    * ``excluded`` — rows removed for structured reasons (invalid inputs,
      missing provenance, INSUFFICIENT quality, missing/unknown source).
    """

    rows: tuple[ProfileStrikeRow, ...]
    total_call_gex: float | None
    total_put_gex: float | None
    total_net_gex: float | None
    greeks_source: str | None
    excluded: tuple[ProfileExclusion, ...] = ()


_EXCLUSION_TEXT = {
    CalculationIssueCode.MISSING_REQUIRED_INPUT: (
        "GEX requires gamma and open interest in contracts for every row; a "
        "required input was missing."
    ),
    CalculationIssueCode.INVALID_INPUT_VALUE: (
        "A row input was invalid (non-finite, negative OI/gamma, or an "
        "unknown greeks source)."
    ),
    CalculationIssueCode.MISSING_PROVENANCE: (
        "The row carries no provenance — it cannot be attributed and is "
        "excluded from the profile."
    ),
    CalculationIssueCode.INSUFFICIENT_QUALITY: (
        "The row's input quality is INSUFFICIENT — required inputs are "
        "unreliable and the row is excluded."
    ),
}


def _exclude(
    reason: CalculationIssueCode, row: OptionMarketData, side: Side
) -> ProfileExclusion:
    return ProfileExclusion(
        reason=reason,
        strike=row.instrument.strike,
        side=side,
        message=_EXCLUSION_TEXT[reason],
    )


def build_gamma_profile(rows: Sequence[OptionMarketData]) -> GammaProfile:
    """Deterministic gamma-profile aggregation across per-side option rows.

    Each row is an :class:`OptionMarketData` for ONE option side carrying an
    explicit gamma, open interest (contracts) and greeks source.  Rules:

    * Structural validation per row; invalid rows are excluded with a
      structured :class:`ProfileExclusion` — never fabricated, never silently
      dropped.
    * All rows must share the same positive finite underlying spot, and all
      *valid* rows must share the same greeks source (BROKER or MODEL) — a
      mixed-source profile raises a deterministic ``ValueError``.
    * Duplicate (strike, side) rows each contribute (each row is a separate
      observation; contributions are summed per (strike, side)).
    * Output rows are sorted by strike ascending; missing sides stay None.
    """
    if not isinstance(rows, Sequence):
        raise TypeError("rows must be a sequence of OptionMarketData")

    excluded: list[ProfileExclusion] = []
    valid: list[OptionMarketData] = []
    spot: float | None = None

    for row in rows:
        if not isinstance(row, OptionMarketData):
            raise TypeError("every profile row must be an OptionMarketData")
        side = row.instrument.option_type
        if row.gamma is None or row.open_interest is None or row.greeks_source is None:
            excluded.append(
                _exclude(CalculationIssueCode.MISSING_REQUIRED_INPUT, row, side)
            )
            continue
        if row.greeks_source not in _GREEKS_SOURCES:
            excluded.append(
                _exclude(CalculationIssueCode.INVALID_INPUT_VALUE, row, side)
            )
            continue
        # numeric validity (the OptionMarketData contract already guards these)
        if (
            not math.isfinite(float(row.gamma))
            or not math.isfinite(float(row.open_interest))
            or float(row.gamma) < 0
            or float(row.open_interest) < 0
            or not math.isfinite(float(row.spot))
            or float(row.spot) <= 0
        ):
            excluded.append(
                _exclude(CalculationIssueCode.INVALID_INPUT_VALUE, row, side)
            )
            continue
        if row.provenance is None:
            excluded.append(
                _exclude(CalculationIssueCode.MISSING_PROVENANCE, row, side)
            )
            continue
        if row.quality is QualityState.INSUFFICIENT:
            excluded.append(
                _exclude(CalculationIssueCode.INSUFFICIENT_QUALITY, row, side)
            )
            continue
        if spot is None:
            spot = float(row.spot)
        elif float(row.spot) != spot:
            raise ValueError(_MSG_SPOT_MISMATCH)
        valid.append(row)

    if not valid:
        return GammaProfile(
            rows=(),
            total_call_gex=None,
            total_put_gex=None,
            total_net_gex=None,
            greeks_source=None,
            excluded=tuple(excluded),
        )

    sources = {row.greeks_source for row in valid}
    if len(sources) != 1:
        raise ValueError(_MSG_MIXED_SOURCES)
    greeks_source = sources.pop()

    # Sum contributions per (strike, side).
    call_by_strike: dict[float, float] = {}
    put_by_strike: dict[float, float] = {}
    for row in valid:
        side = row.instrument.option_type
        contribution = dealer_signed_gex(side, row.gamma, row.open_interest, row.spot)
        bucket = call_by_strike if side is Side.CALL else put_by_strike
        bucket[row.instrument.strike] = bucket.get(row.instrument.strike, 0.0) + contribution

    strikes = sorted(set(call_by_strike) | set(put_by_strike))
    profile_rows: list[ProfileStrikeRow] = []
    for strike in strikes:
        call_gex = call_by_strike.get(strike)
        put_gex = put_by_strike.get(strike)
        net_gex = (call_gex or 0.0) + (put_gex or 0.0)
        profile_rows.append(
            ProfileStrikeRow(strike=strike, call_gex=call_gex, put_gex=put_gex, net_gex=net_gex)
        )

    total_call = (
        sum(r.call_gex for r in profile_rows if r.call_gex is not None)
        if any(r.call_gex is not None for r in profile_rows)
        else None
    )
    total_put = (
        sum(r.put_gex for r in profile_rows if r.put_gex is not None)
        if any(r.put_gex is not None for r in profile_rows)
        else None
    )
    total_net = sum(r.net_gex for r in profile_rows)

    return GammaProfile(
        rows=tuple(profile_rows),
        total_call_gex=total_call,
        total_put_gex=total_put,
        total_net_gex=total_net,
        greeks_source=greeks_source,
        excluded=tuple(excluded),
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class GexCalculationEngine:
    """Deterministic GEX engine (Day 17).

    Implements the Day-14 :class:`~app.quant.boundary.QuantEngine` protocol:
    pure ``calculate(OptionMarketData, CalculationContext) -> QuantResult``.
    The calculation has no time dependence — it never reads the clock.
    """

    calculation_id = CALCULATION_ID
    model = MODEL
    model_version = MODEL_VERSION
    calculation_version = CALCULATION_VERSION
    methodology = METHOD_VERSION
    sign_convention = SIGN_CONVENTION

    def calculate(
        self,
        market_data: OptionMarketData,
        context: CalculationContext,
    ) -> QuantResult:
        """Evaluate per-option raw + dealer-signed GEX."""
        # The boundary already guarantees provenance + quality gates and the
        # OptionMarketData/CalculationContext validation.  Engine-level checks:
        if market_data.gamma is None:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.UNAVAILABLE,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.MISSING_REQUIRED_INPUT,
                        message=_MSG_MISSING_GAMMA,
                        field="gamma",
                    ),
                ),
            )
        if market_data.open_interest is None:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.UNAVAILABLE,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.MISSING_REQUIRED_INPUT,
                        message=_MSG_MISSING_OI,
                        field="open_interest",
                    ),
                ),
            )
        if market_data.greeks_source is None:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.UNAVAILABLE,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.MISSING_REQUIRED_INPUT,
                        message=_MSG_MISSING_SOURCE,
                        field="greeks_source",
                    ),
                ),
            )
        if market_data.greeks_source not in _GREEKS_SOURCES:
            return self._result(
                market_data=market_data,
                context=context,
                status=CalculationStatus.INVALID_INPUT,
                issues=(
                    QuantIssue(
                        code=CalculationIssueCode.INVALID_INPUT_VALUE,
                        message=_MSG_INVALID_SOURCE,
                        field="greeks_source",
                    ),
                ),
            )

        try:
            raw = raw_gex(market_data.gamma, market_data.open_interest, market_data.spot)
            signed = dealer_signed_gex(
                market_data.instrument.option_type,
                market_data.gamma,
                market_data.open_interest,
                market_data.spot,
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
            values={"raw_gex": raw, "signed_gex": signed},
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
            greeks_source=market_data.greeks_source,
        )
