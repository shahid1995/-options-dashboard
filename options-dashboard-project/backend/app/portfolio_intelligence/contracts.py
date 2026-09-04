"""Day 35 — Portfolio Intelligence contracts (pure, broker-neutral).

This module defines the deterministic analytics vocabulary for a portfolio:

* ``PortfolioPosition`` — the normalized, broker-neutral representation of ONE
  authoritative position (paper ``Position`` rows for paper portfolios;
  broker-observed rows for broker portfolios).  It is NOT a new source of
  position truth: it only re-states authoritative quantity/value evidence and
  carries optional per-position Greek / spot / mark evidence supplied by the
  caller.
* Analytical view contracts (exposure / Greek / GEX / scenario sensitivity /
  concentration / directional / regime-aware risk) and the aggregate
  ``PortfolioAnalyticsResult``.

Rules locked here
-----------------
1. **Analytical consumer only.**  Nothing in this package writes positions,
   orders, cash or broker state; nothing contacts a broker, DB, network,
   filesystem, environment or wall clock.
2. **Missing ≠ zero.**  Every optional value is ``None`` when genuinely
   missing; ``0.0`` remains a legitimate measured zero.  Views preserve an
   explicit assessment state (``AVAILABLE`` / ``PARTIAL`` / ``UNAVAILABLE`` /
   ``INVALID``) so an incomplete aggregate is never presented as complete.
3. **Source separation.**  ``source`` on a position distinguishes
   ``PAPER`` (authoritative paper ledger netting) from ``BROKER`` (broker
   observed).  Per-unit Greek inputs carry the canonical Day-9 source
   vocabulary (``BROKER`` | ``MODEL``) and are never mixed inside one
   aggregate total.
4. **Reuse.**  Quantity/direction conventions mirror
   ``app.quant.scenarios.OptionLeg`` (quantity non-negative + explicit
   direction); per-unit Greek units mirror the Day-9 ``GreeksObservation``
   doc; quality uses the Day-9 ``QualityState`` vocabulary; provenance is the
   canonical Day-9 ``Provenance``; the Day-23 ``MarketRegime`` is consumed
   whole.  No second provenance / quality / regime model exists here.
5. **Deterministic serialization.**  ``portfolio_result_to_dict`` /
   ``portfolio_result_from_dict`` round-trip the full result; identical
   inputs serialize to identical bytes.
"""

from __future__ import annotations

import math
import types
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Union, get_args, get_origin, get_type_hints

from app.intelligence.contracts import MarketRegime, RegimeLabel
from app.market_data.contracts import Provenance, QualityState, Side
from app.quant.scenarios import PositionDirection

# ---------------------------------------------------------------------------
# Versions / vocabulary
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "1.0.0"
MODEL_VERSION = "portfolio.intelligence.v1"
CALCULATION_VERSION = "1.0.0"

#: Canonical per-unit Greek source vocabulary (Day-9 ``GreeksObservation``).
GREEKS_SOURCE_BROKER = "BROKER"
GREEKS_SOURCE_MODEL = "MODEL"
GREEKS_SOURCES = frozenset({GREEKS_SOURCE_BROKER, GREEKS_SOURCE_MODEL})

#: Portfolio-owned GEX methodology: the Day-17 raw-GEX formula applied to the
#: portfolio's OWN gamma x OWN contract count x spot (never market OI).  The
#: methodology token mirrors ``app.quant.gex.METHOD_VERSION``.
GEX_METHOD_VERSION = "GEX_STANDARD_V1"


class PortfolioStatus(str, Enum):
    """Top-level analytics status.

    SUCCESS = complete deterministic analysis; PARTIAL = computed with
    incomplete evidence channels; UNAVAILABLE = nothing measurable was
    supplied; INVALID = structurally invalid input (e.g. cross-tenant).
    This vocabulary is analytic only — never PASS/BLOCKED risk-policy words.
    """

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class EvidenceState(str, Enum):
    """Assessment state of one analytical dimension/evidence channel.

    Mirrors the explicit dimension-state vocabulary used across the domain
    (AVAILABLE / PARTIAL / UNAVAILABLE / INVALID) so incomplete evidence is
    never presented as complete.
    """

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class PositionSource(str, Enum):
    """Authoritative origin of a normalized position.

    PAPER = the paper ledger's netted ``Position`` row; BROKER = a
    broker-observed position row.  Never inferred from a label.
    """

    PAPER = "PAPER"
    BROKER = "BROKER"


class DeltaPosture(str, Enum):
    """Descriptive net-delta posture (exposure, not a prediction).

    ``NO_DELTA_EVIDENCE`` when no position supplies a delta — the posture is
    never guessed from a regime label or an option type alone.
    """

    LONG_DELTA = "LONG_DELTA"
    SHORT_DELTA = "SHORT_DELTA"
    DELTA_NEUTRAL = "DELTA_NEUTRAL"
    NO_DELTA_EVIDENCE = "NO_DELTA_EVIDENCE"


class PortfolioIssueCode(str, Enum):
    """Structured, machine-readable portfolio-analytics issue categories."""

    MIXED_TENANT = "MIXED_TENANT"
    MISSING_REFERENCE_TIMESTAMP = "MISSING_REFERENCE_TIMESTAMP"
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"
    MISSING_GREEKS = "MISSING_GREEKS"
    MISSING_GEX_INPUT = "MISSING_GEX_INPUT"
    MISSING_SCENARIO = "MISSING_SCENARIO"
    MISSING_REGIME = "MISSING_REGIME"
    REGIME_UNKNOWN = "REGIME_UNKNOWN"
    NO_DIRECTIONAL_EVIDENCE = "NO_DIRECTIONAL_EVIDENCE"
    EMPTY_PORTFOLIO = "EMPTY_PORTFOLIO"
    INVALID_VALUE = "INVALID_VALUE"


@dataclass(frozen=True)
class PortfolioIssue:
    """A structured issue attached to a portfolio analytics result."""

    code: PortfolioIssueCode
    message: str
    field: str | None = None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_finite_or_none(value: float | None, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number or None")


def _require_non_negative_or_none(value: float | None, name: str) -> None:
    if value is None:
        return
    _require_finite_or_none(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative or None")


def _is_aware(ts: datetime) -> bool:
    if ts.tzinfo is None:
        return False
    return ts.tzinfo.utcoffset(ts) is not None


def _require_aware(ts: datetime, name: str) -> None:
    if not isinstance(ts, datetime):
        raise ValueError(f"{name} must be a datetime")
    if not _is_aware(ts):
        raise ValueError(f"{name} must be genuinely timezone-aware")


def _require_source_token(source: str, name: str = "source") -> None:
    if not isinstance(source, str) or source not in GREEKS_SOURCES:
        raise ValueError(
            f"{name} must be one of {sorted(GREEKS_SOURCES)} "
            "(the canonical Day-9 BROKER/MODEL vocabulary)"
        )


# ---------------------------------------------------------------------------
# Per-position Greek evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GreekInput:
    """Per-unit option Greek evidence for ONE position.

    Units follow the canonical Day-9 ``GreeksObservation`` doc: delta per
    unit, gamma per unit per unit, theta annualized per unit, vega per 1.00
    volatility move per unit, rho per unit.  Every value is optional —
    ``None`` means genuinely missing, never zero.  ``source`` is the
    canonical BROKER | MODEL token so broker and model greeks are never
    silently mixed.  ``provenance`` / ``quality`` are the canonical Day-9
    contracts, preserved verbatim (never synthesized here).
    """

    source: str
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    quality: QualityState | None = None
    provenance: Provenance | None = None
    calc_model: str | None = None
    calc_version: str | None = None

    def __post_init__(self) -> None:
        _require_source_token(self.source)
        for name in ("delta", "gamma", "theta", "vega", "rho"):
            _require_finite_or_none(getattr(self, name), name)
        if self.quality is not None and not isinstance(self.quality, QualityState):
            raise ValueError("quality must be a QualityState or None")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")
        for name in ("calc_model", "calc_version"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)


# ---------------------------------------------------------------------------
# Normalized position
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioPosition:
    """One normalized, broker-neutral authoritative position.

    * Identity — ``underlying`` / ``expiry`` (ISO) / ``strike`` /
      ``option_type`` (canonical ``Side``).
    * Quantity — ``quantity`` (non-negative) x ``direction`` (explicit
      LONG/SHORT, the ONLY sign authority) exactly like the Day-18
      ``OptionLeg`` convention.  For paper portfolios the paper engine's
      netted quantity (in lots) is authoritative; for broker portfolios the
      broker-observed quantity is authoritative.  ``lot_size`` is preserved
      when supplied (never fabricated) and is NOT folded into ``quantity``.
    * Valuation — ``entry_price`` / ``current_price`` / ``market_value`` are
      optional.  ``market_value`` is the authoritative observed value
      (broker-reported for broker rows); missing stays missing.
    * Evidence — optional ``greeks`` (per-unit, sourced), ``spot`` (underlying
      spot at the reference, used for portfolio-owned GEX scaling) and
      ``quality`` / ``provenance`` preserved verbatim.
    * ``reference_timestamp`` — required, caller-supplied, timezone-aware.

    Zero/closed positions are not valid normalized positions (a position with
    no open quantity carries nothing to measure); the paper engine marks
    those CLOSED and the normalization adapters reject them.
    """

    position_id: str
    tenant_id: str
    source: PositionSource
    underlying: str
    expiry: str
    strike: float
    option_type: Side
    quantity: float
    direction: PositionDirection
    lot_size: int | None = None
    entry_price: float | None = None
    current_price: float | None = None
    market_value: float | None = None
    spot: float | None = None
    greeks: GreekInput | None = None
    quality: QualityState | None = None
    provenance: Provenance | None = None
    reference_timestamp: datetime = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _require_text(self.position_id, "position_id")
        _require_text(self.tenant_id, "tenant_id")
        if not isinstance(self.source, PositionSource):
            raise ValueError("source must be a PositionSource")
        _require_text(self.underlying, "underlying")
        try:
            datetime.strptime(self.expiry, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"expiry must be an ISO YYYY-MM-DD date, got {self.expiry!r}"
            ) from exc
        if not isinstance(self.strike, (int, float)) or not math.isfinite(self.strike):
            raise ValueError("strike must be a finite number")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if not isinstance(self.option_type, Side) or self.option_type not in (
            Side.CALL,
            Side.PUT,
        ):
            raise ValueError("option_type must be Side.CALL or Side.PUT")
        if not isinstance(self.quantity, (int, float)) or not math.isfinite(self.quantity):
            raise ValueError("quantity must be a finite number")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive (closed/empty positions are not positions)")
        if not isinstance(self.direction, PositionDirection):
            raise ValueError("direction must be PositionDirection.LONG or SHORT")
        if self.lot_size is not None and (
            not isinstance(self.lot_size, int) or self.lot_size < 1
        ):
            raise ValueError("lot_size must be a positive integer or None")
        for name in ("entry_price", "current_price", "market_value", "spot"):
            _require_non_negative_or_none(getattr(self, name), name)
        if self.greeks is not None and not isinstance(self.greeks, GreekInput):
            raise ValueError("greeks must be a GreekInput or None")
        if self.quality is not None and not isinstance(self.quality, QualityState):
            raise ValueError("quality must be a QualityState or None")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")
        _require_aware(self.reference_timestamp, "reference_timestamp")

    @property
    def signed_quantity(self) -> float:
        """Signed quantity: direction.sign x quantity (the only sign source)."""
        return self.direction.sign * self.quantity


# ---------------------------------------------------------------------------
# Exposure analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExposureSlice:
    """One deterministic slice of the signed exposure view."""

    key: str
    signed_quantity: float
    absolute_quantity: float
    position_count: int


@dataclass(frozen=True)
class PortfolioExposure:
    """Descriptive signed exposure across the authoritative positions.

    ``signed_quantity_total`` is the measured net of signed quantities in the
    authoritative position unit (paper: lots; broker: broker contracts).  The
    layer never converts lots to contracts (that would require inventing a
    multiplier).  Market value is summed ONLY over positions that actually
    supply an observed ``market_value``; the rest are listed as missing —
    a missing value never contributes zero.
    """

    state: EvidenceState
    position_count: int
    signed_quantity_total: float
    long_quantity_total: float
    short_quantity_total: float
    quantity_unit: str
    market_value_total: float | None
    market_value_positions: int
    positions_missing_market_value: tuple[str, ...]
    by_expiry: tuple[ExposureSlice, ...]
    by_option_type: tuple[ExposureSlice, ...]
    by_direction: tuple[ExposureSlice, ...]
    issues: tuple[PortfolioIssue, ...] = ()


# ---------------------------------------------------------------------------
# Greek analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GreekContribution:
    """One position's exposure-scaled Greek contribution.

    Scaling follows the authoritative Day-18 convention used by
    ``evaluate_leg``: per-unit Greek x direction.sign x quantity.  Each value
    stays ``None`` when the per-unit input was missing (never zero).
    """

    position_id: str
    greeks_source: str
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None
    quality: QualityState | None
    provenance: Provenance | None


@dataclass(frozen=True)
class GreekSourceTotal:
    """Exposure-scaled aggregate Greeks for ONE Greek source.

    Mirror of ``GexSourceTotal``: broker-observed and model-derived Greek
    evidence are NEVER summed into one number.  Each component total sums
    only the positions OF THIS SOURCE that supplied that Greek; a missing
    component stays ``None`` (never zero) and ``state`` reflects the source's
    coverage (``AVAILABLE`` complete / ``PARTIAL`` incomplete /
    ``UNAVAILABLE`` when the source supplied no usable Greek).
    ``contributing_positions`` / ``missing_positions`` keep every total
    traceable to its positions.
    """

    source: str
    delta_total: float | None
    gamma_total: float | None
    theta_total: float | None
    vega_total: float | None
    rho_total: float | None
    contributing_positions: tuple[str, ...]
    missing_positions: tuple[str, ...]
    state: EvidenceState


@dataclass(frozen=True)
class PortfolioGreekExposure:
    """Aggregate per-unit Greeks scaled by signed quantity, by Greek source.

    ``by_source`` holds ONE ``GreekSourceTotal`` per contributing source
    (deterministic sorted order), so broker and model evidence never mix in
    an aggregate; when only one source exists it is exposed alone.  ``sources``
    lists the contributing sources sorted; ``contributions`` preserves every
    position's source/quality/provenance; missing components stay ``None``
    and the overall state reflects incomplete coverage (``PARTIAL``) or
    total absence (``UNAVAILABLE``).
    """

    state: EvidenceState
    by_source: tuple[GreekSourceTotal, ...]
    sources: tuple[str, ...]
    contributions: tuple[GreekContribution, ...]
    missing_positions: tuple[str, ...]
    issues: tuple[PortfolioIssue, ...] = ()


# ---------------------------------------------------------------------------
# Portfolio-owned GEX analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GexSourceTotal:
    """Portfolio-owned GEX total for one Greek source.

    Methodology is the Day-17 raw-GEX formula applied to the portfolio's own
    gamma x own contract count x spot, signed by the explicit position
    direction.  Own contract count = quantity x lot_size when the multiplier
    is supplied, else quantity (documented per position input).  This is
    NEVER the market/dealer GEX (which uses market open interest and the
    dealer sign convention).
    """

    source: str
    signed_gex_total: float | None
    contributing_positions: tuple[str, ...]
    missing_positions: tuple[str, ...]
    state: EvidenceState


@dataclass(frozen=True)
class PortfolioGexExposure:
    """Portfolio gamma exposure measured in GEX units (raw-GEX methodology).

    ``methodology`` mirrors the Day-17 methodology token; the formula is
    reused from ``app.quant.gex.raw_gex`` — no second GEX formula exists
    here.  Missing gamma or missing spot makes a position's GEX contribution
    unavailable (never zero); a mixed gamma source yields one total per
    source.
    """

    state: EvidenceState
    methodology: str
    by_source: tuple[GexSourceTotal, ...]
    issues: tuple[PortfolioIssue, ...] = ()


# ---------------------------------------------------------------------------
# Scenario sensitivity analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioRow:
    """One SUPPLIED portfolio scenario row (authoritative Day-18 output).

    Supplied by the caller from the existing Scenario & Time Analysis engine
    (``app.quant.scenarios``) — this layer aggregates, it never re-evaluates.
    ``tenant_id`` ties the row to one portfolio tenant.  ``total_pnl`` is the
    portfolio total at the point when fully priced; ``partial=True`` rows
    carry no P/L (missing never becomes zero).
    """

    tenant_id: str
    point_id: str
    spot: float
    time_to_expiry: float
    implied_volatility: float
    total_pnl: float | None = None
    partial: bool = False
    quality: QualityState | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        _require_text(self.tenant_id, "tenant_id")
        _require_text(self.point_id, "point_id")
        for name in ("spot", "time_to_expiry", "implied_volatility"):
            _require_finite_or_none(getattr(self, name), name)
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive")
        _require_finite_or_none(self.total_pnl, "total_pnl")
        if self.quality is not None and not isinstance(self.quality, QualityState):
            raise ValueError("quality must be a QualityState or None")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")


@dataclass(frozen=True)
class PortfolioScenarioSensitivity:
    """Aggregated supplied scenario sensitivity.

    Preserves scenario identity (per-row ``point_id`` and coordinates),
    partial/incomplete state and per-row provenance/quality.  P/L aggregates
    are computed only over complete rows; partial rows never contribute a
    zero P/L.
    """

    state: EvidenceState
    rows: tuple[ScenarioRow, ...]
    point_count: int
    complete_rows: int
    partial_rows: int
    worst_supplied_pnl: float | None
    worst_supplied_point_id: str | None
    best_supplied_pnl: float | None
    issues: tuple[PortfolioIssue, ...] = ()


# ---------------------------------------------------------------------------
# Concentration / directional / regime views
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConcentrationSlice:
    """One deterministic concentration slice of a dimension."""

    key: str
    exposure: float
    share: float
    position_count: int


@dataclass(frozen=True)
class LargestAbsoluteExposure:
    """The largest absolute exposure (measured; ties broken by id order)."""

    position_id: str
    absolute_exposure: float


@dataclass(frozen=True)
class ConcentrationView:
    """Descriptive concentration measurement.

    Basis: absolute normalized quantity per position (the same authoritative
    quantity unit as the exposure view).  Concentration is a measurement:
    the view carries no danger/high-risk/trade/avoid classification and no
    threshold verdict.
    """

    state: EvidenceState
    basis: str
    by_strike: tuple[ConcentrationSlice, ...]
    by_expiry: tuple[ConcentrationSlice, ...]
    by_option_type: tuple[ConcentrationSlice, ...]
    largest_absolute: LargestAbsoluteExposure | None = None
    issues: tuple[PortfolioIssue, ...] = ()


@dataclass(frozen=True)
class DirectionalView:
    """Descriptive portfolio directional exposure from actual delta evidence.

    Net delta is exposure-scaled (per-unit delta x signed quantity).  The
    posture describes the measured sign of net delta only; it is NOT a
    probability, forecast, trade signal or recommendation, and no regime or
    option-type label can manufacture it.
    """

    state: EvidenceState
    net_delta: float | None
    delta_posture: DeltaPosture
    call_delta: float | None
    put_delta: float | None
    long_delta: float | None
    short_delta: float | None
    positions_with_delta: int
    positions_total: int
    missing_delta_positions: tuple[str, ...]
    issues: tuple[PortfolioIssue, ...] = ()


@dataclass(frozen=True)
class RegimeRiskView:
    """Regime-aware risk view (contextual, never directional fabrication).

    Consumes the authoritative Day-23 ``MarketRegime`` whole.  The regime
    label is contextual evidence ONLY: it never produces a directional
    claim.  ``net_delta_context`` restates the portfolio's measured net delta
    when delta evidence exists; without it the view stays PARTIAL/UNAVAILABLE
    and guesses nothing.  Unknown/unavailable regimes remain unknown.
    """

    state: EvidenceState
    regime: MarketRegime | None
    regime_label: RegimeLabel | None
    net_delta_context: float | None
    delta_posture_context: DeltaPosture
    notes: tuple[str, ...] = ()
    issues: tuple[PortfolioIssue, ...] = ()


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioAnalyticsResult:
    """Deterministic structured portfolio analytics result.

    Channel separation is explicit: authoritative position state (echoed
    normalized ``positions``), exposure, Greeks, portfolio-owned GEX,
    scenario sensitivity, concentration, directional and regime-aware views
    stay separate — this aggregate is analytics, never a risk-policy
    decision, capital/margin decision or execution authorization.
    """

    status: PortfolioStatus
    positions: tuple[PortfolioPosition, ...]
    exposure: PortfolioExposure
    greeks: PortfolioGreekExposure
    gex: PortfolioGexExposure
    scenarios: PortfolioScenarioSensitivity
    concentration: ConcentrationView
    directional: DirectionalView
    regime_risk: RegimeRiskView
    quality: QualityState | None
    position_quality_states: tuple[QualityState | None, ...]
    issues: tuple[PortfolioIssue, ...]
    provenance: Provenance | None
    reference_timestamp: datetime
    contract_version: str = CONTRACT_VERSION
    model_version: str = MODEL_VERSION
    calculation_version: str = CALCULATION_VERSION


# ---------------------------------------------------------------------------
# Deterministic serialization (full round trip)
# ---------------------------------------------------------------------------


def _to_jsonable(value):
    """Recursively convert a frozen-dataclass tree to JSON-safe values.

    Enums become their ``.value``; aware datetimes become ISO strings;
    dataclasses become ordered dicts; tuples become lists.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    return value


def _resolve_union(ann):
    """Strip ``None``/``NoneType`` members out of a typing union."""
    args = [a for a in get_args(ann) if a is not type(None)]  # noqa: E721
    if len(args) == 1:
        return args[0]
    return typing.Union[tuple(args)] if args else type(None)


def _rebuild(ann, value):
    """Rebuild one annotated value from JSON-safe data (annotation-guided)."""
    if value is None:
        return None
    origin = get_origin(ann)
    if origin is Union or origin is types.UnionType:
        return _rebuild(_resolve_union(ann), value)
    if origin is tuple:
        item_ann = get_args(ann)[0] if get_args(ann) else typing.Any
        return tuple(_rebuild(item_ann, item) for item in value)
    if origin is list:
        item_ann = get_args(ann)[0] if get_args(ann) else typing.Any
        return [_rebuild(item_ann, item) for item in value]
    # Annotations may arrive as strings only when hints are unresolved.
    if isinstance(ann, str):
        return value
    if isinstance(ann, type) and is_dataclass(ann):
        return _from_dict(ann, value)
    if isinstance(ann, type):
        if issubclass(ann, Enum):
            return ann(value)
        if issubclass(ann, datetime):
            return datetime.fromisoformat(value)
        if issubclass(ann, float):
            return float(value)
        if issubclass(ann, int) and not issubclass(ann, bool):
            return int(value)
    return value


def _from_dict(cls, data: dict):
    """Rebuild one dataclass from its JSON-safe dict using its annotations."""
    hints = get_type_hints(cls, include_extras=True)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = _rebuild(hints.get(f.name, typing.Any), data[f.name])
    return cls(**kwargs)


def portfolio_result_to_dict(result: PortfolioAnalyticsResult) -> dict:
    """Deterministic JSON-safe dict for the full analytics result."""
    if not isinstance(result, PortfolioAnalyticsResult):
        raise TypeError("portfolio_result_to_dict requires a PortfolioAnalyticsResult")
    return _to_jsonable(result)


def portfolio_result_from_dict(data: dict) -> PortfolioAnalyticsResult:
    """Rebuild the full analytics result from ``portfolio_result_to_dict``."""
    if not isinstance(data, dict):
        raise TypeError("portfolio_result_from_dict requires a dict")
    return _from_dict(PortfolioAnalyticsResult, data)


__all__ = [
    "CALCULATION_VERSION",
    "CONTRACT_VERSION",
    "GEX_METHOD_VERSION",
    "GREEKS_SOURCE_BROKER",
    "GREEKS_SOURCE_MODEL",
    "GREEKS_SOURCES",
    "MODEL_VERSION",
    "ConcentrationSlice",
    "ConcentrationView",
    "DeltaPosture",
    "DirectionalView",
    "EvidenceState",
    "ExposureSlice",
    "GexSourceTotal",
    "GreekContribution",
    "GreekInput",
    "GreekSourceTotal",
    "LargestAbsoluteExposure",
    "PortfolioAnalyticsResult",
    "PortfolioExposure",
    "PortfolioGexExposure",
    "PortfolioGreekExposure",
    "PortfolioIssue",
    "PortfolioIssueCode",
    "PortfolioPosition",
    "PortfolioScenarioSensitivity",
    "PortfolioStatus",
    "PositionSource",
    "RegimeRiskView",
    "ScenarioRow",
    "portfolio_result_from_dict",
    "portfolio_result_to_dict",
]
