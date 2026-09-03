"""Day 20 — Positioning Intelligence engine.

Deterministic, broker-neutral OI/positioning interpretation on the Day-19
Intelligence Contract::

    Raw strike-level observations (OI / ΔOI / volume / price context)
        -> derived metrics (totals, ratios, asymmetry, concentration)
        -> deterministic change-based chain classification
        -> Day-19 IntelligenceResult (direction / signal_strength /
           confidence / evidence / quality / provenance)

Layers stay separate (master-plan Day-20 gate): :class:`StrikePositioning`
rows are raw observations, :func:`compute_metrics` derives metrics,
:func:`classify_chain` produces the classification, and
:func:`evaluate_positioning` maps classification + metrics into the
authoritative :class:`~app.intelligence.contracts.IntelligenceResult`.

Rules
-----
1. Missing values stay ``None`` — never coerced to zero.  A measured zero is
   a legitimate zero.  Missing OI/price data yields structured
   PARTIAL/UNAVAILABLE results, never a fabricated read.
2. Classification is **change-based only** (net ΔOI × price direction):
   LONG_BUILDUP / SHORT_BUILDUP / SHORT_COVERING / LONG_UNWINDING.  Static
   level facts (e.g. the highest-OI strike) are reported as measured
   concentration data only — they are never interpreted as support or
   resistance (Day-21 scope).
3. Conflicting CE/PE evidence is reported MIXED with the Day-19
   ``CONFLICTING_DIRECTION`` issue — never forced to a side.
4. signal_strength != confidence != data quality.  The exact supplied Day-12
   :class:`QualityResult` and Day-9 :class:`Provenance` are preserved
   verbatim; quality is never recomputed.
5. Pure and deterministic: no wall clock, randomness, network, filesystem,
   database or broker imports.  Timestamps come only from the input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    INTELLIGENCE_CONTRACT_VERSION,
    EvidenceType,
    IntelligenceDirection,
    IntelligenceEvidence,
    IntelligenceIssue,
    IntelligenceIssueCode,
    IntelligenceObservation,
    IntelligenceResult,
    IntelligenceStatus,
    TimeHorizon,
)

# ---------------------------------------------------------------------------
# Identity / versioning
# ---------------------------------------------------------------------------

CALCULATION_ID = "intelligence.positioning.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Documented magnitude reference for signal-strength normalization (contracts).
#: ``strength = min(|net ΔOI| / STRENGTH_REFERENCE_OI, 1.0)``.
STRENGTH_REFERENCE_OI = 1_000_000.0

#: Documented deterministic confidence table (completeness-based).
CONFIDENCE_FULL = 0.90      # both ΔOI legs + price context present
CONFIDENCE_SINGLE_LEG = 0.65  # classification rests on one ΔOI leg
CONFIDENCE_NO_PRICE = 0.40  # OI totals present, price context missing
CONFIDENCE_CONFLICT = 0.50  # opposing CE/PE evidence

#: Directional mapping of the deterministic chain labels.
_LABEL_DIRECTION = {
    "LONG_BUILDUP": IntelligenceDirection.BULLISH,
    "SHORT_BUILDUP": IntelligenceDirection.BEARISH,
    "SHORT_COVERING": IntelligenceDirection.BULLISH,
    "LONG_UNWINDING": IntelligenceDirection.BEARISH,
}


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class PositioningClassification(str, Enum):
    """Deterministic chain classification (change-based only)."""

    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    SHORT_COVERING = "SHORT_COVERING"
    LONG_UNWINDING = "LONG_UNWINDING"
    UNCLASSIFIED = "UNCLASSIFIED"


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _finite_or_none(value, name: str) -> None:
    if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
        raise ValueError(f"{name} must be a finite number or None")


def _non_negative_or_none(value, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


# ---------------------------------------------------------------------------
# Raw input layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrikePositioning:
    """One strike row of raw, canonical positioning observations.

    OI and volume are in **contracts** (never lots).  Every measurement is
    ``float | None`` — ``None`` is genuinely missing (never coerced to 0.0);
    a measured 0.0 is a legitimate zero.
    """

    strike: float
    call_oi: float | None = None
    put_oi: float | None = None
    call_oi_change: float | None = None
    put_oi_change: float | None = None
    call_volume: float | None = None
    put_volume: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strike, (int, float)) or not math.isfinite(self.strike):
            raise ValueError("strike must be a finite number")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        # OI levels and volumes are non-negative; OI changes are signed (OI
        # can decrease) — only their finiteness is validated.
        for name in ("call_oi", "put_oi", "call_volume", "put_volume"):
            _non_negative_or_none(getattr(self, name), name)
        for name in ("call_oi_change", "put_oi_change"):
            _finite_or_none(getattr(self, name), name)


@dataclass(frozen=True)
class PositioningInput:
    """Canonical input to the positioning engine for one underlying chain.

    ``spot``/``spot_change`` are the price context (absolute, signed).  All
    timestamps are explicit and timezone-aware; the engine never reads the
    wall clock.  ``quality`` is the preserved Day-12 assessment (``None`` is
    allowed and yields a non-SUCCESS result, never a fabricated read).
    """

    underlying: str
    rows: tuple[StrikePositioning, ...]
    reference_timestamp: datetime
    provenance: Provenance
    expiry: str | None = None
    spot: float | None = None
    spot_change: float | None = None
    window_seconds: float | None = None
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        _finite_or_none(self.spot, "spot")
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive when present")
        _finite_or_none(self.spot_change, "spot_change")
        if not isinstance(self.rows, tuple) or not all(
            isinstance(r, StrikePositioning) for r in self.rows
        ):
            raise ValueError("rows must be a tuple of StrikePositioning")
        if not _aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        if self.window_seconds is not None and (
            not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(self.window_seconds) or self.window_seconds <= 0
        ):
            raise ValueError("window_seconds must be a finite positive number or None")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Day-9 Provenance")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")


# ---------------------------------------------------------------------------
# Derived metric layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositioningMetrics:
    """Deterministic derived positioning metrics.

    ``None`` = the underlying series is missing (never coerced to zero);
    a measured 0.0 stays a legitimate zero.  Concentration facts are
    measurements only — never interpreted as levels.
    """

    total_call_oi: float | None = None
    total_put_oi: float | None = None
    put_call_oi_ratio: float | None = None
    total_call_oi_change: float | None = None
    total_put_oi_change: float | None = None
    net_chain_oi_change: float | None = None
    ce_pe_oi_change_asymmetry: float | None = None
    total_call_volume: float | None = None
    total_put_volume: float | None = None
    put_call_volume_ratio: float | None = None
    max_call_oi_strike: float | None = None
    max_put_oi_strike: float | None = None
    max_abs_oi_change_strike: float | None = None
    call_oi_side_present: bool = False
    put_oi_side_present: bool = False
    call_change_side_present: bool = False
    put_change_side_present: bool = False


def _sum_side(rows, attr: str):
    values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return (sum(values), bool(values))


def _ratio(numerator, denominator) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0.0:
        return None  # measured zero denominator — no ratio
    return numerator / denominator


def _max_by(rows, key):
    """Deterministic argmax by ``key(row)``; ties resolved to the LOWER strike."""
    best = None
    best_value = None
    for r in rows:
        value = key(r)
        if value is None:
            continue
        if best is None or value > best_value or (
            value == best_value and r.strike < best.strike
        ):
            best = r
            best_value = value
    return best.strike if best is not None else None


def compute_metrics(inp: PositioningInput) -> PositioningMetrics:
    """Compute the deterministic derived metrics (never fabricates data)."""
    rows = inp.rows
    call_oi, call_oi_present = _sum_side(rows, "call_oi")
    put_oi, put_oi_present = _sum_side(rows, "put_oi")
    call_d, call_d_present = _sum_side(rows, "call_oi_change")
    put_d, put_d_present = _sum_side(rows, "put_oi_change")
    call_v, call_v_present = _sum_side(rows, "call_volume")
    put_v, put_v_present = _sum_side(rows, "put_volume")

    call_oi = call_oi if call_oi_present else None
    put_oi = put_oi if put_oi_present else None
    call_d = call_d if call_d_present else None
    put_d = put_d if put_d_present else None
    call_v = call_v if call_v_present else None
    put_v = put_v if put_v_present else None

    net = call_d + put_d if (call_d_present and put_d_present) else None
    asym = call_d - put_d if (call_d_present and put_d_present) else None

    return PositioningMetrics(
        total_call_oi=call_oi,
        total_put_oi=put_oi,
        put_call_oi_ratio=_ratio(put_oi, call_oi),
        total_call_oi_change=call_d,
        total_put_oi_change=put_d,
        net_chain_oi_change=net,
        ce_pe_oi_change_asymmetry=asym,
        total_call_volume=call_v,
        total_put_volume=put_v,
        put_call_volume_ratio=_ratio(put_v, call_v),
        max_call_oi_strike=_max_by(rows, lambda r: r.call_oi),
        max_put_oi_strike=_max_by(rows, lambda r: r.put_oi),
        max_abs_oi_change_strike=_max_by(
            rows,
            lambda r: max(
                abs(r.call_oi_change) if r.call_oi_change is not None else -1.0,
                abs(r.put_oi_change) if r.put_oi_change is not None else -1.0,
            )
            if r.call_oi_change is not None or r.put_oi_change is not None
            else None,
        ),
        call_oi_side_present=call_oi_present,
        put_oi_side_present=put_oi_present,
        call_change_side_present=call_d_present,
        put_change_side_present=put_d_present,
    )


# ---------------------------------------------------------------------------
# Classification layer (change-based only)
# ---------------------------------------------------------------------------


def classify_chain(
    net_oi_change: float | None,
    spot_change: float | None,
) -> PositioningClassification:
    """Deterministic chain classification from net ΔOI and price direction.

    Change-based only — static OI levels never classify.  Missing inputs,
    a balanced net (0.0) or an unchanged price (0.0) all yield
    ``UNCLASSIFIED``.
    """
    if net_oi_change is None or spot_change is None:
        return PositioningClassification.UNCLASSIFIED
    if net_oi_change == 0.0 or spot_change == 0.0:
        return PositioningClassification.UNCLASSIFIED
    if net_oi_change > 0:
        return (
            PositioningClassification.LONG_BUILDUP
            if spot_change > 0
            else PositioningClassification.SHORT_BUILDUP
        )
    return (
        PositioningClassification.SHORT_COVERING
        if spot_change > 0
        else PositioningClassification.LONG_UNWINDING
    )


def classification_direction(
    label: PositioningClassification,
) -> IntelligenceDirection | None:
    """Documented deterministic label → direction mapping (None when
    UNCLASSIFIED — neutral/mixed/unknown are decided by the caller from the
    evidence)."""
    return _LABEL_DIRECTION.get(label.value)


def _legs_conflict(metrics: PositioningMetrics) -> bool:
    """True when CE and PE ΔOI are both non-trivial and oppose each other."""
    c, p = metrics.total_call_oi_change, metrics.total_put_oi_change
    if c is None or p is None:
        return False
    if c == 0.0 or p == 0.0:
        return False
    return (c > 0.0) != (p > 0.0)


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _ref(inp: PositioningInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"pos:{inp.underlying}:{scope}:{key}"


def _ev(inp: PositioningInput, key: str, value: float | None, unit: str | None,
        kind: EvidenceType) -> IntelligenceEvidence:
    return IntelligenceEvidence(
        source_reference_id=_ref(inp, key),
        evidence_type=kind,
        value=value,
        unit=unit,
        reference_timestamp=inp.reference_timestamp,
        provenance=inp.provenance,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )


def _raw_evidence(inp: PositioningInput, metrics: PositioningMetrics):
    out = []
    pairs = [
        ("total_call_oi", metrics.total_call_oi),
        ("total_put_oi", metrics.total_put_oi),
        ("total_call_oi_change", metrics.total_call_oi_change),
        ("total_put_oi_change", metrics.total_put_oi_change),
        ("total_call_volume", metrics.total_call_volume),
        ("total_put_volume", metrics.total_put_volume),
    ]
    for key, value in pairs:
        if value is not None:
            out.append(_ev(inp, key, value, "contracts", EvidenceType.MARKET_OBSERVATION))
    if inp.spot is not None:
        out.append(_ev(inp, "spot", float(inp.spot), "points", EvidenceType.MARKET_OBSERVATION))
    if inp.spot_change is not None:
        out.append(_ev(inp, "spot_change", float(inp.spot_change), "points",
                        EvidenceType.MARKET_OBSERVATION))
    return out


def _derived_evidence(inp: PositioningInput, metrics: PositioningMetrics):
    out = []
    pairs = [
        ("put_call_oi_ratio", metrics.put_call_oi_ratio, None),
        ("put_call_volume_ratio", metrics.put_call_volume_ratio, None),
        ("net_chain_oi_change", metrics.net_chain_oi_change, "contracts"),
        ("ce_pe_oi_change_asymmetry", metrics.ce_pe_oi_change_asymmetry, "contracts"),
    ]
    for key, value, unit in pairs:
        if value is not None:
            out.append(_ev(inp, key, float(value), unit, EvidenceType.QUANT_DERIVED))
    for key, strike in (
        ("max_call_oi_strike", metrics.max_call_oi_strike),
        ("max_put_oi_strike", metrics.max_put_oi_strike),
        ("max_abs_oi_change_strike", metrics.max_abs_oi_change_strike),
    ):
        if strike is not None:
            out.append(_ev(inp, key, float(strike), "points", EvidenceType.QUANT_DERIVED))
    return out


# ---------------------------------------------------------------------------
# Interpretation layer
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code, message=code.value, field=field)


def _has_usable_rows(inp: PositioningInput, metrics: PositioningMetrics) -> bool:
    if not inp.rows:
        return False
    return any(
        v is not None
        for v in (
            metrics.total_call_oi, metrics.total_put_oi,
            metrics.total_call_oi_change, metrics.total_put_oi_change,
            metrics.total_call_volume, metrics.total_put_volume,
        )
    )


def evaluate_positioning(inp: PositioningInput) -> IntelligenceResult:
    """Evaluate positioning for one chain and return the authoritative
    Day-19 :class:`IntelligenceResult`."""
    metrics = compute_metrics(inp)
    evidence = _raw_evidence(inp, metrics) + _derived_evidence(inp, metrics)
    issues: list[IntelligenceIssue] = []
    direction: IntelligenceDirection | None = None
    strength: float | None = None
    confidence: float | None = None
    status: IntelligenceStatus | None = None
    observation: IntelligenceObservation | None = None

    def finish() -> IntelligenceResult:
        horizon = TimeHorizon.EXPIRY if status is IntelligenceStatus.SUCCESS else None
        return IntelligenceResult(
            calculation_id=CALCULATION_ID,
            status=status or IntelligenceStatus.UNAVAILABLE,
            direction=direction,
            signal_strength=strength,
            confidence=confidence,
            time_horizon=horizon,
            observation=observation,
            evidence=tuple(evidence),
            regime=None,
            quality=inp.quality,
            provenance=inp.provenance,
            reference_timestamp=inp.reference_timestamp,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version=MODEL_VERSION,
            calculation_version=CALCULATION_VERSION,
            issues=tuple(issues),
        )

    # -- no usable data -----------------------------------------------------
    if not _has_usable_rows(inp, metrics):
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "rows"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        status = IntelligenceStatus.UNAVAILABLE
        evidence = []  # UNAVAILABLE carries no evidence by contract
        return finish()

    if inp.quality is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        direction = None
        return finish()

    # -- classification completeness ----------------------------------------
    net = metrics.net_chain_oi_change
    spot_change = inp.spot_change
    conflict = _legs_conflict(metrics)

    if conflict:
        # opposing CE/PE evidence — report mixed, never forced to a side
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.CONFLICTING_DIRECTION, "ce_pe_oi_change"))
        direction = IntelligenceDirection.MIXED
        combined = abs(metrics.total_call_oi_change or 0.0) + abs(
            metrics.total_put_oi_change or 0.0
        )
        strength = min(combined / STRENGTH_REFERENCE_OI, 1.0)
        confidence = CONFIDENCE_CONFLICT
        if net is not None:
            observation = IntelligenceObservation(
                metric_name="net_chain_oi_change", value=float(net), unit="contracts"
            )
        return finish()

    if net is not None and spot_change is not None:
        label = classify_chain(net, spot_change)
        if label is not PositioningClassification.UNCLASSIFIED:
            status = IntelligenceStatus.SUCCESS
            direction = classification_direction(label)
            strength = min(abs(net) / STRENGTH_REFERENCE_OI, 1.0)
            confidence = CONFIDENCE_FULL
            observation = IntelligenceObservation(
                metric_name="net_chain_oi_change", value=float(net), unit="contracts"
            )
            return finish()
        # balanced net or flat price → neutral (measured, not missing)
        status = IntelligenceStatus.SUCCESS
        direction = IntelligenceDirection.NEUTRAL
        strength = 0.0
        confidence = CONFIDENCE_FULL
        if net is not None:
            observation = IntelligenceObservation(
                metric_name="net_chain_oi_change", value=float(net), unit="contracts"
            )
        return finish()

    # -- partial data -------------------------------------------------------
    status = IntelligenceStatus.PARTIAL
    if net is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "put_oi_change" if not metrics.put_change_side_present
                             else "call_oi_change"))
    if spot_change is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT, "spot_change"))
    direction = None
    confidence = CONFIDENCE_NO_PRICE if spot_change is None else CONFIDENCE_SINGLE_LEG
    if net is not None:
        observation = IntelligenceObservation(
            metric_name="net_chain_oi_change", value=float(net), unit="contracts"
        )
    return finish()
