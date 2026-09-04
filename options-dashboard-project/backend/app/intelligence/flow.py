"""Day 20 — Flow / Divergence Intelligence engine.

Deterministic, broker-neutral flow and divergence interpretation on the
Day-19 Intelligence Contract::

    Chain-level raw series (CE/PE ΔOI, volumes, greek shifts, price context)
        -> derived flow series (CE-PE net flow, directional imbalance,
           price-flow relation, delta divergence, vega pattern)
        -> Day-19 IntelligenceResult (direction / signal_strength /
           confidence / evidence / quality / provenance)

Rules
-----
1. Greek shifts (delta/vega) are **inputs** — the engine never computes
   Greeks; Day-15 quant outputs feed it upstream.  Conventions: OI/volume in
   contracts; ``call_delta_shift`` and ``put_delta_shift`` are signed
   directional delta of each side's OI change (put-side negative);
   ``vega_shift_net`` is the signed net vega exposure change of the window.
2. Missing values stay ``None`` — never coerced to zero; a measured zero
   stays a legitimate zero.  Missing series yield structured
   PARTIAL/UNAVAILABLE results.
3. Divergence flags are **measured patterns** (price and a positioning series
   moved in opposite directions) — never unconditional outcomes.  Conflicting
   evidence is reported MIXED with the Day-19 ``CONFLICTING_DIRECTION`` issue,
   never forced to a side.
4. Primary directional series is ``net_delta_shift`` when present, else
   ``net_ce_pe_flow`` (documented deterministic fallback).  The read is
   confirmed by price direction when the signs agree.
5. signal_strength != confidence != data quality.  The exact supplied Day-12
   :class:`QualityResult` and Day-9 :class:`Provenance` are preserved
   verbatim; quality is never recomputed.
6. Pure and deterministic: no wall clock, randomness, network, filesystem,
   database or broker imports.
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

CALCULATION_ID = "intelligence.flow_divergence.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Documented magnitude reference for signal-strength normalization (contracts
#: / notional-delta units).  ``strength = min(|primary| / FLOW_REFERENCE, 1)``.
FLOW_REFERENCE = 1_000_000.0

#: Documented deterministic confidence table.
CONFIDENCE_FULL = 0.90      # delta shift + flow + price all present
CONFIDENCE_FLOW_FALLBACK = 0.85  # delta shift missing, flow + price present
CONFIDENCE_DIVERGENCE = 0.50  # conflicting price vs positioning evidence
CONFIDENCE_NO_PRICE = 0.40  # positioning series present, price missing


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class PriceFlowRelation(str, Enum):
    """Deterministic tri-state: price direction vs a positioning series."""

    CONFIRM = "CONFIRM"
    DIVERGE = "DIVERGE"
    NO_SIGNAL = "NO_SIGNAL"


class VegaPattern(str, Enum):
    """Deterministic vega-positioning pattern vs price direction."""

    VOL_DEMAND_WITH_PRICE = "VOL_DEMAND_WITH_PRICE"
    VOL_DEMAND_AGAINST_PRICE = "VOL_DEMAND_AGAINST_PRICE"
    NO_SIGNAL = "NO_SIGNAL"


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


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
class FlowInput:
    """Canonical chain-level flow input (explicit, provenance-stamped).

    All series are ``float | None`` — ``None`` is missing (never coerced to
    zero).  Volume is non-negative; ΔOI, delta and vega shifts are signed.
    Timestamps are explicit and timezone-aware.
    """

    underlying: str
    reference_timestamp: datetime
    provenance: Provenance
    expiry: str | None = None
    spot: float | None = None
    spot_change: float | None = None
    net_ce_oi_change: float | None = None
    net_pe_oi_change: float | None = None
    ce_volume: float | None = None
    pe_volume: float | None = None
    call_delta_shift: float | None = None
    put_delta_shift: float | None = None
    vega_shift_net: float | None = None
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.underlying, str) or not self.underlying.strip():
            raise ValueError("underlying must be a non-empty string")
        if self.expiry is not None and (not isinstance(self.expiry, str) or not self.expiry.strip()):
            raise ValueError("expiry must be a non-empty string or None")
        _finite_or_none(self.spot, "spot")
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive when present")
        _finite_or_none(self.spot_change, "spot_change")
        _finite_or_none(self.net_ce_oi_change, "net_ce_oi_change")
        _finite_or_none(self.net_pe_oi_change, "net_pe_oi_change")
        _non_negative_or_none(self.ce_volume, "ce_volume")
        _non_negative_or_none(self.pe_volume, "pe_volume")
        _finite_or_none(self.call_delta_shift, "call_delta_shift")
        _finite_or_none(self.put_delta_shift, "put_delta_shift")
        _finite_or_none(self.vega_shift_net, "vega_shift_net")
        if not _aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Day-9 Provenance")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")


# ---------------------------------------------------------------------------
# Derived metric layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowMetrics:
    """Deterministic derived flow/divergence series (None when missing)."""

    net_ce_pe_flow: float | None = None
    directional_imbalance: float | None = None
    net_delta_shift: float | None = None
    price_flow_relation: PriceFlowRelation | None = None
    delta_divergence: PriceFlowRelation | None = None
    vega_pattern: VegaPattern | None = None


def _relation(price: float | None, series: float | None) -> PriceFlowRelation | None:
    """CONFIRM when both non-zero and same sign; DIVERGE when opposed;
    NO_SIGNAL when either is zero; None when either is missing."""
    if price is None or series is None:
        return None
    if price == 0.0 or series == 0.0:
        return PriceFlowRelation.NO_SIGNAL
    return PriceFlowRelation.CONFIRM if (price > 0.0) == (series > 0.0) else PriceFlowRelation.DIVERGE


def _vega_pattern(price: float | None, vega: float | None) -> VegaPattern | None:
    if price is None or vega is None:
        return None
    if price == 0.0 or vega == 0.0:
        return VegaPattern.NO_SIGNAL
    same = (price > 0.0) == (vega > 0.0)
    return VegaPattern.VOL_DEMAND_WITH_PRICE if same else VegaPattern.VOL_DEMAND_AGAINST_PRICE


def compute_flow_metrics(inp: FlowInput) -> FlowMetrics:
    """Compute the deterministic derived flow/divergence series."""
    net_flow = None
    if inp.net_ce_oi_change is not None and inp.net_pe_oi_change is not None:
        net_flow = inp.net_ce_oi_change - inp.net_pe_oi_change

    imbalance = None
    if inp.ce_volume is not None and inp.pe_volume is not None:
        total_vol = inp.ce_volume + inp.pe_volume
        if total_vol != 0.0:
            imbalance = (inp.ce_volume - inp.pe_volume) / total_vol

    net_delta = None
    if inp.call_delta_shift is not None and inp.put_delta_shift is not None:
        net_delta = inp.call_delta_shift + inp.put_delta_shift

    return FlowMetrics(
        net_ce_pe_flow=net_flow,
        directional_imbalance=imbalance,
        net_delta_shift=net_delta,
        price_flow_relation=_relation(inp.spot_change, net_flow),
        delta_divergence=_relation(inp.spot_change, net_delta),
        vega_pattern=_vega_pattern(inp.spot_change, inp.vega_shift_net),
    )


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _ref(inp: FlowInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"flow:{inp.underlying}:{scope}:{key}"


def _ev(inp: FlowInput, key: str, value: float | None, unit: str | None,
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


def _build_evidence(inp: FlowInput, m: FlowMetrics):
    out = []
    raw_pairs = [
        ("net_ce_oi_change", inp.net_ce_oi_change),
        ("net_pe_oi_change", inp.net_pe_oi_change),
        ("ce_volume", inp.ce_volume),
        ("pe_volume", inp.pe_volume),
        ("call_delta_shift", inp.call_delta_shift),
        ("put_delta_shift", inp.put_delta_shift),
        ("vega_shift_net", inp.vega_shift_net),
    ]
    for key, value in raw_pairs:
        if value is not None:
            unit = "contracts" if "volume" in key or "_oi_" in key else "notional"
            out.append(_ev(inp, key, float(value), unit, EvidenceType.MARKET_OBSERVATION))
    if inp.spot is not None:
        out.append(_ev(inp, "spot", float(inp.spot), "points", EvidenceType.MARKET_OBSERVATION))
    if inp.spot_change is not None:
        out.append(_ev(inp, "spot_change", float(inp.spot_change), "points",
                        EvidenceType.MARKET_OBSERVATION))

    derived_pairs = [
        ("net_ce_pe_flow", m.net_ce_pe_flow, "contracts"),
        ("directional_imbalance", m.directional_imbalance, None),
        ("net_delta_shift", m.net_delta_shift, "notional"),
    ]
    for key, value, unit in derived_pairs:
        if value is not None:
            out.append(_ev(inp, key, float(value), unit, EvidenceType.QUANT_DERIVED))
    # Categorical divergence flags (price_flow_relation, delta_divergence,
    # vega_pattern) live in the derived-metric layer (FlowMetrics) — they are
    # not numeric measurements and are never forced into numeric evidence.
    if inp.quality is not None:
        out.append(IntelligenceEvidence(
            source_reference_id=f"flow:{inp.underlying}:{inp.expiry or 'chain'}:quality",
            evidence_type=EvidenceType.QUALITY_ASSESSMENT,
            value=float(inp.quality.quality_score),
            unit="score_0_100",
            reference_timestamp=inp.reference_timestamp,
            provenance=inp.provenance,
            model_version=MODEL_VERSION,
            calculation_version=CALCULATION_VERSION,
        ))
    return out


def _issue(code: IntelligenceIssueCode, field: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code, message=code.value, field=field)


# ---------------------------------------------------------------------------
# Interpretation layer
# ---------------------------------------------------------------------------


def _primary_series(inp: FlowInput, m: FlowMetrics):
    """Documented deterministic primary series: delta shift, else CE-PE flow."""
    if m.net_delta_shift is not None:
        return m.net_delta_shift, "net_delta_shift", "notional"
    if m.net_ce_pe_flow is not None:
        return m.net_ce_pe_flow, "net_ce_pe_flow", "contracts"
    return None, None, None


def _any_series(inp: FlowInput, m: FlowMetrics) -> bool:
    return any(
        v is not None
        for v in (
            inp.net_ce_oi_change, inp.net_pe_oi_change, inp.ce_volume,
            inp.pe_volume, inp.call_delta_shift, inp.put_delta_shift,
            inp.vega_shift_net, inp.spot, inp.spot_change,
        )
    )


def evaluate_flow(inp: FlowInput) -> IntelligenceResult:
    """Evaluate flow/divergence for one chain and return the authoritative
    Day-19 :class:`IntelligenceResult`."""
    m = compute_flow_metrics(inp)
    evidence = _build_evidence(inp, m)
    primary, metric_name, unit = _primary_series(inp, m)

    direction: IntelligenceDirection | None = None
    strength: float | None = None
    confidence: float | None = None
    status: IntelligenceStatus | None = None
    issues: list[IntelligenceIssue] = []
    observation: IntelligenceObservation | None = None
    fallback = metric_name == "net_ce_pe_flow"

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

    if not _any_series(inp, m):
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "series"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        status = IntelligenceStatus.UNAVAILABLE
        evidence = []  # UNAVAILABLE carries no evidence by contract
        return finish()

    if inp.quality is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return finish()

    if primary is None:
        # nothing directional at all (may still have volume evidence)
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT, "primary_series"))
        return finish()

    price = inp.spot_change
    if price is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT, "spot_change"))
        direction = None
        confidence = CONFIDENCE_NO_PRICE
        observation = IntelligenceObservation(
            metric_name=metric_name, value=float(primary), unit=unit
        )
        return finish()

    magnitude = abs(primary)
    strength = min(magnitude / FLOW_REFERENCE, 1.0)
    observation = IntelligenceObservation(
        metric_name=metric_name, value=float(primary), unit=unit
    )

    if primary == 0.0 or price == 0.0:
        # no directional flow (balanced) or no price confirmation
        status = IntelligenceStatus.SUCCESS
        direction = IntelligenceDirection.NEUTRAL
        strength = 0.0
        confidence = CONFIDENCE_FLOW_FALLBACK if fallback else CONFIDENCE_FULL
        return finish()

    if (primary > 0.0) == (price > 0.0):
        # price confirms the directional positioning series
        status = IntelligenceStatus.SUCCESS
        direction = IntelligenceDirection.BULLISH if primary > 0.0 else IntelligenceDirection.BEARISH
        confidence = CONFIDENCE_FLOW_FALLBACK if fallback else CONFIDENCE_FULL
        return finish()

    # price opposes the directional positioning series — conflicting evidence
    status = IntelligenceStatus.PARTIAL
    issues.append(_issue(IntelligenceIssueCode.CONFLICTING_DIRECTION, "price_vs_primary"))
    direction = IntelligenceDirection.MIXED
    confidence = CONFIDENCE_DIVERGENCE
    return finish()
