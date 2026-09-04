"""Day 21 — Dynamic Support/Resistance Intelligence Engine.

Deterministic, broker-neutral dynamic-level interpretation on the Day-19
Intelligence Contract, consuming Day-20 raw strike rows::

    Raw strike rows (Day-20 StrikePositioning) -> chain context
        -> candidates (measured concentration facts)
        -> derived level evidence (shares / activity / interaction)
        -> SUPPORT/RESISTANCE classification (typed layer)
        -> per-level Day-19 IntelligenceResult (positional, evidence-linked)

Layers stay separate: raw observations, chain-context derived metrics,
per-strike candidates, the typed classification layer and the intelligence
interpretation envelope are distinct public surfaces.

Core principle
--------------
**A high-OI strike is a measured concentration fact, NOT automatically
support or resistance.**  Static concentration alone never classifies: a
level requires significant side concentration AND at least one corroborating
component (strengthening/active ΔOI, volume activity, price approach or
side asymmetry).  Corroboration by standing asymmetry alone yields a
``STATIC`` level — explicitly no dynamic confirmation (historical price
reactions are never fabricated: no canonical historical-touch interface
exists, and gamma-wall level evidence is deferred because no canonical
gamma-wall interface exists — Day-17 explicitly excluded gamma walls).

Price interaction semantics
---------------------------
Price moving TOWARD a level is a weak interaction (``APPROACHING``): it
proves movement, not that the level was tested, respected, rejected or
confirmed.  ``CONFIRMED_INTERACTION`` is therefore **reserved** for a future
explicit historical-touch/rejection evidence interface and is never produced
by current Day-21 inputs.  A level the price demonstrably moved THROUGH
(support breakdown below / resistance breakout above) is
``CONFLICTED_INTERACTION``.  Missing price context is never an interaction.

Rules
-----
1. Missing values stay ``None`` — never coerced to zero; a measured zero is a
   legitimate zero; shares are ``None`` when a component (or its chain
   maximum) is missing.
2. Balanced CE/PE evidence at a strike => ``UNCLASSIFIED`` /
   ``MIXED_EVIDENCE`` — never forced to a side.
3. Levels are **positional, not directional**: interpretation results always
   carry ``direction=NEUTRAL``.  ``level_strength != confidence != quality``.
   Strength is the equal mean of PRESENT normalized components (missing
   component != 0, no hidden weights); ``APPROACHING`` contributes nothing
   (approach is not confirmation); ``CONFLICTED`` contributes a documented
   0.0 (an observed, demonstrably-broken level).  Confidence is a documented
   completeness table.
4. The exact supplied Day-12 :class:`QualityResult` and Day-9
   :class:`Provenance` are preserved verbatim; quality is never recomputed.
   Missing quality or an INSUFFICIENT quality state gates SUCCESS.
5. Nearby same-kind levels merge deterministically by strike distance
   (``CLUSTER_STRIKE_DISTANCE``, inclusive); different kinds never merge.
6. Pure and deterministic: no wall clock, randomness, network, filesystem,
   database or broker imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance
from app.market_data.quality import QualityResult, QualityState
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
from app.intelligence.positioning import StrikePositioning

# ---------------------------------------------------------------------------
# Identity / versioning / documented policy constants
# ---------------------------------------------------------------------------

CALCULATION_ID = "intelligence.levels.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: A side is "significant" when its OI is at least this share of the chain
#: side maximum (documented concentration threshold).
CONCENTRATION_THRESHOLD = 0.5

#: A ΔOI/volume component is "active" at or above this share of the chain
#: side maximum (documented activity threshold).
ACTIVITY_THRESHOLD = 0.5

#: Same-kind classified levels merge when their strikes are at most this far
#: apart (absolute strike distance, inclusive boundary — documented).
CLUSTER_STRIKE_DISTANCE = 50.0

#: Documented deterministic confidence table (completeness-based).
CONFIDENCE_FULL = 0.90      # classifying side ΔOI present AND price present
CONFIDENCE_NO_PRICE = 0.50  # price context missing
CONFIDENCE_NO_SIDE_DELTA = 0.65  # classifying side's ΔOI missing
CONFIDENCE_OTHER = 0.80


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class LevelKind(str, Enum):
    """Deterministic level classification (evidence-kind, never folklore)."""

    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"
    UNCLASSIFIED = "UNCLASSIFIED"


class LevelState(str, Enum):
    """Dynamic state of a candidate/level.

    ``STATIC`` — concentration (+ standing asymmetry) only: the data supports
    a measured level but no dynamic confirmation exists (never fabricated).
    ``APPROACHING`` — price moving toward the level (weak interaction; never
    confirmation).  ``CONFIRMED_INTERACTION`` is **reserved** for a future
    explicit historical-touch/rejection evidence interface; current Day-21
    inputs never produce it.  ``MIXED_EVIDENCE`` — balanced CE and PE
    evidence at the same strike.
    """

    STATIC = "STATIC"
    STRENGTHENING = "STRENGTHENING"
    WEAKENING = "WEAKENING"
    APPROACHING = "APPROACHING"
    CONFIRMED_INTERACTION = "CONFIRMED_INTERACTION"
    CONFLICTED_INTERACTION = "CONFLICTED_INTERACTION"
    MIXED_EVIDENCE = "MIXED_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class _Interaction(str, Enum):
    """Internal price-interaction classification for one strike.

    ``APPROACHING`` — price moving toward the level (weak; never confirms).
    ``CONFLICTED`` — price demonstrably through the level (breakdown/out).
    """

    NONE = "NONE"
    APPROACHING = "APPROACHING"
    CONFLICTED = "CONFLICTED"


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


def _aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _share(value, maximum) -> float | None:
    """Deterministic normalized share in [0,1]; None when either is missing
    or the (measured zero) maximum is 0."""
    if value is None or maximum is None:
        return None
    if maximum == 0.0:
        return None
    return abs(value) / maximum


# ---------------------------------------------------------------------------
# Raw input layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelInput:
    """Canonical level-engine input for one underlying chain.

    ``rows`` reuse the Day-20 :class:`StrikePositioning` raw observations;
    ``spot``/``spot_change`` provide price context.  Timestamps are explicit
    and genuinely timezone-aware; ``quality`` is the preserved Day-12
    assessment (None is allowed and yields non-SUCCESS results).
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
# Derived layer: chain context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainContext:
    """Per-side maxima over the chain (derived metrics; None when a side is
    absent).  All shares elsewhere are measured against these."""

    max_call_oi: float | None = None
    max_put_oi: float | None = None
    max_call_abs_delta: float | None = None
    max_put_abs_delta: float | None = None
    max_call_volume: float | None = None
    max_put_volume: float | None = None


def _max_present(rows, attr):
    """Max of the present values; ΔOI maxima use absolute magnitudes (OI
    changes are signed)."""
    values = [abs(getattr(r, attr)) for r in rows if getattr(r, attr) is not None]
    if not values:
        return None
    return max(values)


def derive_chain_context(inp: LevelInput) -> ChainContext:
    """Derive deterministic per-side maxima over the chain."""
    return ChainContext(
        max_call_oi=_max_present(inp.rows, "call_oi"),
        max_put_oi=_max_present(inp.rows, "put_oi"),
        max_call_abs_delta=_max_present(inp.rows, "call_oi_change"),
        max_put_abs_delta=_max_present(inp.rows, "put_oi_change"),
        max_call_volume=_max_present(inp.rows, "call_volume"),
        max_put_volume=_max_present(inp.rows, "put_volume"),
    )


# ---------------------------------------------------------------------------
# Classification layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelClassification:
    """Typed per-strike classification (raw → derived → classification).

    ``kind`` is the evidence-kind classification; ``state`` describes the
    dynamic evidence; ``strength`` is the bounded equal-mean of present
    normalized components (None for UNCLASSIFIED strikes).
    """

    strike: float
    kind: LevelKind
    state: LevelState
    strength: float | None = None


def _approaching_for_kind(kind: LevelKind, strike: float, spot,
                          spot_change) -> bool:
    """Kind-aware approach: price moving TOWARD the level from its
    load-bearing side — a support approached from above (falling) or a
    resistance approached from below (rising).  An approach is a weak
    interaction only: it proves movement, never that the level was tested or
    rejected.  Moves away from the level, wrong-side moves, exact-touch
    prices and missing price context are not approaches."""
    if spot is None or spot_change is None or spot_change == 0.0:
        return False
    if spot == strike:
        return False
    if kind is LevelKind.SUPPORT:
        return spot > strike and spot_change < 0.0
    if kind is LevelKind.RESISTANCE:
        return spot < strike and spot_change > 0.0
    return False


def _conflict_for_kind(kind: LevelKind, strike: float, spot, spot_change) -> bool:
    """Kind-aware price conflict: a support that price has broken DOWN through
    (price below the strike and still falling), or a resistance that price has
    broken UP through (price above the strike and still rising)."""
    if spot is None or spot_change is None or spot_change == 0.0:
        return False
    if kind is LevelKind.SUPPORT:
        return spot < strike and spot_change < 0.0
    if kind is LevelKind.RESISTANCE:
        return spot > strike and spot_change > 0.0
    return False


def _interaction(kind: LevelKind, strike: float, spot, spot_change) -> _Interaction:
    if _conflict_for_kind(kind, strike, spot, spot_change):
        return _Interaction.CONFLICTED
    if _approaching_for_kind(kind, strike, spot, spot_change):
        return _Interaction.APPROACHING
    return _Interaction.NONE


def _classify_strike(row: StrikePositioning, ctx: ChainContext,
                     inp: LevelInput) -> LevelClassification:
    spot = inp.spot
    spot_change = inp.spot_change

    call_share = _share(row.call_oi, ctx.max_call_oi)
    put_share = _share(row.put_oi, ctx.max_put_oi)
    call_delta_share = _share(row.call_oi_change, ctx.max_call_abs_delta)
    put_delta_share = _share(row.put_oi_change, ctx.max_put_abs_delta)
    call_vol_share = _share(row.call_volume, ctx.max_call_volume)
    put_vol_share = _share(row.put_volume, ctx.max_put_volume)

    support_approach = _approaching_for_kind(LevelKind.SUPPORT, row.strike,
                                              spot, spot_change)
    resistance_approach = _approaching_for_kind(LevelKind.RESISTANCE,
                                                 row.strike, spot, spot_change)

    def side_dynamic(delta, delta_share, activity_share):
        """STRENGTHENING / WEAKENING / None for the classifying side."""
        if delta is None or delta_share is None:
            return None
        if delta > 0.0 and delta_share >= ACTIVITY_THRESHOLD:
            return LevelState.STRENGTHENING
        if delta < 0.0 and delta_share >= ACTIVITY_THRESHOLD:
            return LevelState.WEAKENING
        return None

    call_dynamic = side_dynamic(row.call_oi_change, call_delta_share, ACTIVITY_THRESHOLD)
    put_dynamic = side_dynamic(row.put_oi_change, put_delta_share, ACTIVITY_THRESHOLD)

    # Corroborators per side (evidence components — never folklore).
    call_corroborated = (
        call_dynamic is not None
        or (call_vol_share is not None and call_vol_share >= ACTIVITY_THRESHOLD)
        or resistance_approach
        or (row.call_oi is not None and row.put_oi is not None
            and row.call_oi > row.put_oi)  # call-heavy standing asymmetry
    )
    put_corroborated = (
        put_dynamic is not None
        or (put_vol_share is not None and put_vol_share >= ACTIVITY_THRESHOLD)
        or support_approach
        or (row.put_oi is not None and row.call_oi is not None
            and row.put_oi > row.call_oi)  # put-heavy standing asymmetry
    )

    call_significant = call_share is not None and call_share >= CONCENTRATION_THRESHOLD
    put_significant = put_share is not None and put_share >= CONCENTRATION_THRESHOLD

    resistance = call_significant and call_corroborated
    support = put_significant and put_corroborated

    if resistance and support:
        return LevelClassification(row.strike, LevelKind.UNCLASSIFIED,
                                   LevelState.MIXED_EVIDENCE, None)
    if resistance:
        interaction = _interaction(LevelKind.RESISTANCE, row.strike, spot, spot_change)
        state = _pick_state(interaction, call_dynamic)
        return LevelClassification(
            row.strike, LevelKind.RESISTANCE, state,
            _strength([call_share, call_delta_share, call_vol_share, interaction]),
        )
    if support:
        interaction = _interaction(LevelKind.SUPPORT, row.strike, spot, spot_change)
        state = _pick_state(interaction, put_dynamic)
        return LevelClassification(
            row.strike, LevelKind.SUPPORT, state,
            _strength([put_share, put_delta_share, put_vol_share, interaction]),
        )
    # no classification: static concentration only (measured fact) or nothing
    if call_significant or put_significant:
        return LevelClassification(row.strike, LevelKind.UNCLASSIFIED,
                                   LevelState.STATIC, None)
    return LevelClassification(row.strike, LevelKind.UNCLASSIFIED,
                               LevelState.INSUFFICIENT_EVIDENCE, None)


def _pick_state(interaction: _Interaction, dynamic: LevelState | None) -> LevelState:
    """Documented state priority: conflict > approaching > ΔOI dynamic >
    static.  ``CONFIRMED_INTERACTION`` is reserved for future explicit
    historical-touch evidence and is never produced by current inputs."""
    if interaction is _Interaction.CONFLICTED:
        return LevelState.CONFLICTED_INTERACTION
    if interaction is _Interaction.APPROACHING:
        return LevelState.APPROACHING
    if dynamic is not None:
        return dynamic
    return LevelState.STATIC


def _strength(components) -> float | None:
    """Bounded equal-mean of PRESENT components (missing != 0).  Interaction
    contributes 0.0 only on conflict — treated as a documented observed
    component (the level was demonstrably broken through).  NONE and
    APPROACHING are excluded: approach is a weak interaction, never
    confirmation, so it adds nothing; missing interaction is not zero."""
    present = []
    for comp in components:
        if comp is None:
            continue
        if isinstance(comp, _Interaction):
            if comp is _Interaction.CONFLICTED:
                present.append(0.0)
            # NONE / APPROACHING: excluded — see docstring
            continue
        present.append(float(comp))
    if not present:
        return None
    value = sum(present) / len(present)
    return max(0.0, min(1.0, value))


def classify_levels(inp: LevelInput) -> tuple[LevelClassification, ...]:
    """Classify every strike row deterministically (strike-ascending order)."""
    ctx = derive_chain_context(inp)
    out = [
        _classify_strike(row, ctx, inp)
        for row in sorted(inp.rows, key=lambda r: r.strike)
    ]
    return tuple(out)


# ---------------------------------------------------------------------------
# Clustering layer (deterministic, strike-distance based)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelCluster:
    """A merged zone of same-kind classified levels.

    Same-kind levels merge when their strikes are at most
    ``CLUSTER_STRIKE_DISTANCE`` apart (inclusive); the representative strike
    is the member with the highest strength (deterministic tie-break: lower
    strike).  Different kinds never merge; same-kind strikes separated by a
    different-kind level never chain through it.
    """

    kind: LevelKind
    min_strike: float
    max_strike: float
    representative_strike: float
    members: tuple[LevelClassification, ...]


def build_clusters(
    classifications: tuple[LevelClassification, ...],
) -> tuple[LevelCluster, ...]:
    """Merge classified levels into deterministic strike-distance clusters."""
    classified = [c for c in classifications if c.kind is not LevelKind.UNCLASSIFIED]
    clusters: list[LevelCluster] = []
    current: list[LevelClassification] = []
    for c in classified:
        if current and c.strike - current[-1].strike > CLUSTER_STRIKE_DISTANCE:
            clusters.append(_seal(current))
            current = []
        # a different kind always starts a fresh cluster
        if current and current[-1].kind is not c.kind:
            clusters.append(_seal(current))
            current = []
        current.append(c)
    if current:
        clusters.append(_seal(current))
    clusters.sort(key=lambda cl: cl.min_strike)
    return tuple(clusters)


def _seal(members: list[LevelClassification]) -> LevelCluster:
    best = max(members, key=lambda m: (m.strength if m.strength is not None else -1.0,
                                       -m.strike))
    return LevelCluster(
        kind=members[0].kind,
        min_strike=min(m.strike for m in members),
        max_strike=max(m.strike for m in members),
        representative_strike=best.strike,
        members=tuple(sorted(members, key=lambda m: m.strike)),
    )


# ---------------------------------------------------------------------------
# Interpretation layer
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None,
           message: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code,
                             message=message or code.value,
                             field=field)


def _ref(inp: LevelInput, strike: float, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"lvl:{inp.underlying}:{scope}:{strike:g}:{key}"


def _ev(inp: LevelInput, strike: float, key: str, value: float, unit: str | None,
        kind: EvidenceType) -> IntelligenceEvidence:
    return IntelligenceEvidence(
        source_reference_id=_ref(inp, strike, key),
        evidence_type=kind,
        value=value,
        unit=unit,
        reference_timestamp=inp.reference_timestamp,
        provenance=inp.provenance,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )


def _row_evidence(inp: LevelInput, row: StrikePositioning,
                  ctx: ChainContext, rep: LevelClassification) -> list[IntelligenceEvidence]:
    out: list[IntelligenceEvidence] = []
    raw = [
        ("call_oi", row.call_oi, "contracts"),
        ("put_oi", row.put_oi, "contracts"),
        ("call_oi_change", row.call_oi_change, "contracts"),
        ("put_oi_change", row.put_oi_change, "contracts"),
        ("call_volume", row.call_volume, "contracts"),
        ("put_volume", row.put_volume, "contracts"),
    ]
    for key, value, unit in raw:
        if value is not None:
            out.append(_ev(inp, rep.strike, key, float(value), unit,
                           EvidenceType.MARKET_OBSERVATION))
    if inp.spot is not None:
        out.append(_ev(inp, rep.strike, "spot", float(inp.spot), "points",
                       EvidenceType.MARKET_OBSERVATION))
    if inp.spot_change is not None:
        out.append(_ev(inp, rep.strike, "spot_change", float(inp.spot_change),
                       "points", EvidenceType.MARKET_OBSERVATION))

    side = "call" if rep.kind is LevelKind.RESISTANCE else "put"
    share = {
        "call": _share(row.call_oi, ctx.max_call_oi),
        "put": _share(row.put_oi, ctx.max_put_oi),
    }[side]
    delta_share = {
        "call": _share(row.call_oi_change, ctx.max_call_abs_delta),
        "put": _share(row.put_oi_change, ctx.max_put_abs_delta),
    }[side]
    vol_share = {
        "call": _share(row.call_volume, ctx.max_call_volume),
        "put": _share(row.put_volume, ctx.max_put_volume),
    }[side]

    derived = [
        (f"{side}_share", share, None),
        (f"{side}_delta_share", delta_share, None),
        (f"{side}_volume_share", vol_share, None),
    ]
    for key, value, unit in derived:
        if value is not None:
            out.append(_ev(inp, rep.strike, key, float(value), unit,
                           EvidenceType.QUANT_DERIVED))
    if row.call_oi is not None and row.put_oi is not None:
        asym = row.put_oi - row.call_oi  # signed put-minus-call standing OI
        out.append(_ev(inp, rep.strike, "put_minus_call_oi", float(asym),
                       "contracts", EvidenceType.QUANT_DERIVED))
    if inp.quality is not None:
        out.append(_ev(inp, rep.strike, "quality_score",
                       float(inp.quality.quality_score), "score_0_100",
                       EvidenceType.QUALITY_ASSESSMENT))
    return out


def _confidence(inp: LevelInput, rep: LevelClassification) -> float:
    """Documented completeness-based confidence (separate from strength and
    quality)."""
    side = "call" if rep.kind is LevelKind.RESISTANCE else "put"
    row = next(r for r in inp.rows if r.strike == rep.strike)
    side_delta = getattr(row, f"{side}_oi_change")
    if inp.spot_change is None:
        return CONFIDENCE_NO_PRICE
    if side_delta is None:
        return CONFIDENCE_NO_SIDE_DELTA
    return CONFIDENCE_FULL


def evaluate_levels(inp: LevelInput) -> tuple[IntelligenceResult, ...]:
    """Evaluate one chain and return one Day-19 IntelligenceResult per
    classified level cluster (deterministic order).  Levels are positional —
    direction is always NEUTRAL; level classification lives in the typed
    classification layer."""
    ctx = derive_chain_context(inp)
    classifications = classify_levels(inp)
    clusters = build_clusters(classifications)
    results: list[IntelligenceResult] = []

    global_issue: IntelligenceIssue | None = None
    if inp.quality is None:
        global_issue = _issue(IntelligenceIssueCode.MISSING_QUALITY, "quality")
    elif inp.quality.quality_state is QualityState.INSUFFICIENT:
        global_issue = _issue(IntelligenceIssueCode.INSUFFICIENT_QUALITY,
                              "quality",
                              "input quality is below the interpretability floor")

    for cluster in clusters:
        rep = next(m for m in cluster.members
                   if m.strike == cluster.representative_strike)
        row = next(r for r in inp.rows if r.strike == rep.strike)
        evidence = _row_evidence(inp, row, ctx, rep)
        strength = rep.strength
        issues: list[IntelligenceIssue] = []

        status = IntelligenceStatus.SUCCESS
        direction = IntelligenceDirection.NEUTRAL
        signal_strength = strength
        if global_issue is not None:
            status = IntelligenceStatus.PARTIAL
            issues.append(global_issue)
            direction = None
            signal_strength = None
        elif rep.state is LevelState.CONFLICTED_INTERACTION:
            # price interaction conflicts with the level evidence — reported,
            # never forced (levels are positional; no directional claim)
            status = IntelligenceStatus.PARTIAL
            issues.append(_issue(
                IntelligenceIssueCode.PARTIAL_EVIDENCE,
                "price_interaction",
                "price interaction conflicts with the level evidence",
            ))
            direction = None
            signal_strength = None

        horizon = TimeHorizon.EXPIRY if status is IntelligenceStatus.SUCCESS else None
        results.append(IntelligenceResult(
            calculation_id=CALCULATION_ID,
            status=status,
            direction=direction,
            signal_strength=signal_strength,
            confidence=_confidence(inp, rep) if signal_strength is not None else None,
            time_horizon=horizon,
            observation=IntelligenceObservation(
                metric_name="level_strength",
                value=float(strength) if strength is not None else 0.0,
                unit="score_0_1",
            ),
            evidence=tuple(evidence),
            regime=None,
            quality=inp.quality,
            provenance=inp.provenance,
            reference_timestamp=inp.reference_timestamp,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version=MODEL_VERSION,
            calculation_version=CALCULATION_VERSION,
            issues=tuple(issues),
        ))

    # deterministic order by the cluster's representative strike
    results.sort(key=lambda r: _cluster_rep_strike(r, clusters))
    return tuple(results)


def _cluster_rep_strike(result: IntelligenceResult,
                        clusters: tuple[LevelCluster, ...]) -> float:
    """Map a level result back to its cluster representative strike by the
    first member strike found in the result's evidence keys (deterministic)."""
    for cluster in clusters:
        marker = f":{cluster.representative_strike:g}:"
        if any(marker in e.source_reference_id for e in result.evidence):
            return cluster.representative_strike
    return float("inf")
