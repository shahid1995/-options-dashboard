"""Day 22 — Institutional-Like Activity Intelligence Engine.

Deterministic, broker-neutral **institutional-LIKE** activity interpretation
on the Day-19 Intelligence Contract.  Consumes the canonical chain metrics of
the Day-20 positioning/flow engines (mapped by the caller from
``PositioningMetrics``/``FlowMetrics``) and the Day-21 typed
``LevelClassification`` rows::

    Day-20 chain metrics + Day-21 typed levels
        -> derived context (net ΔOI, CE-PE flow, volume imbalance,
                            delta/vega shifts, proximate levels)
        -> deterministic pattern cascade
        -> exactly one Day-19 IntelligenceResult per evaluation

Compliance
----------
Outputs describe **observable evidence patterns** in INSTITUTIONAL_LIKE
language only.  This engine never claims to identify any specific
participant or institution — it detects large-player-LIKE signatures
(documented scale references) from public option-chain observations.  No
hidden order flow, inventory, execution intent or historical persistence is
ever fabricated.

Pattern cascade (deterministic — exactly one result per evaluation)
-------------------------------------------------------------------
1. ``POSITION_FLOW_CONFLICT`` — cross-series or level evidence opposes price
   (delta shift vs price, net vega demand vs price, or a proximate Day-21
   CONFLICTED_INTERACTION level).  Emitted as PARTIAL + MIXED +
   CONFLICTING_DIRECTION: conflicting evidence is never forced bullish or
   bearish.
2. ``OI_BUILDUP_CONFIRMED`` — net chain ΔOI >= OI_ACTIVITY_FLOOR with a
   usable price direction (accumulation-style; Day-20 change-based
   convention: rising price => LONG_BUILDUP-style BULLISH, falling price =>
   SHORT_BUILDUP-style BEARISH).
3. ``OI_UNWINDING_CONFIRMED`` — net chain ΔOI <= -OI_ACTIVITY_FLOOR with a
   usable price direction (unwinding/distribution-style; Day-20 convention:
   rising => SHORT_COVERING-style BULLISH, falling => LONG_UNWINDING-style
   BEARISH).
4. ``VOLUME_IMBALANCE_FLOW`` — total volume >= VOLUME_ACTIVITY_FLOOR and
   |volume_imbalance| >= IMBALANCE_THRESHOLD when no OI pattern fired
   (aggressive-looking flow; imbalance agreeing with price => SUCCESS,
   opposing price => PARTIAL + MIXED conflict).
5. ``NO_PATTERN`` — usable measured series exist but nothing above fired
   (including a measured flat price).  SUCCESS + NEUTRAL + strength 0.0.

Non-pattern statuses mirror Day-20/21: no usable evidence => UNAVAILABLE;
missing quality => PARTIAL + MISSING_QUALITY; missing price or an incomplete
ΔOI leg (with no stronger pattern) => PARTIAL + MISSING_REQUIRED_INPUT.

Rules
-----
1. Missing stays ``None`` — never coerced to zero; a measured 0.0 stays a
   legitimate zero.  SUCCESS rests only on present, finite evidence.
2. ``signal_strength != confidence != quality`` — separate fields; the exact
   Day-12 :class:`QualityResult` and Day-9 :class:`Provenance` are preserved
   verbatim; quality is never recomputed.
3. Scale references are documented absolute floors (no per-underlying
   typicals exist yet — that requires history, which is never fabricated).
4. Pure and deterministic: no wall clock, randomness, network, filesystem,
   database, broker or services imports.
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
from app.intelligence.levels import LevelClassification, LevelKind, LevelState

# ---------------------------------------------------------------------------
# Identity / versioning / documented policy constants
# ---------------------------------------------------------------------------

CALCULATION_ID = "intelligence.institutional_like.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Minimum |net chain ΔOI| (contracts) for an OI-based INSTITUTIONAL_LIKE
#: pattern — a conservative documented absolute scale reference.  A
#: per-underlying typical baseline requires history and is deferred.
OI_ACTIVITY_FLOOR = 200_000.0

#: Minimum total chain volume (contracts) for a volume-imbalance pattern.
VOLUME_ACTIVITY_FLOOR = 200_000.0

#: |volume_imbalance| must reach this bound for a volume-imbalance pattern.
IMBALANCE_THRESHOLD = 0.5

#: Magnitude references for signal-strength normalization (mirror the
#: documented Day-20 references).
OI_STRENGTH_REFERENCE = 1_000_000.0
DELTA_STRENGTH_REFERENCE = 1_000_000.0

#: A classified level is "proximate" when its strike is within this fraction
#: of spot (deterministic; spot must be present and positive).
LEVEL_PROXIMITY_FRACTION = 0.10

#: Documented deterministic confidence table (completeness-based).
CONFIDENCE_FULL = 0.90       # both ΔOI legs + price + volume present
CONFIDENCE_IMBALANCE = 0.85  # volume-imbalance read produced
CONFIDENCE_SINGLE_SIDE = 0.65  # volume series absent
CONFIDENCE_NO_PRICE = 0.40   # price context missing
CONFIDENCE_CONFLICT = 0.50   # conflicting cross-series/level evidence


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class ActivityPattern(str, Enum):
    """Deterministic INSTITUTIONAL_LIKE evidence patterns (never participant
    identity claims).  The pattern id is carried by the observation
    ``metric_name`` of the emitted result."""

    OI_BUILDUP_CONFIRMED = "OI_BUILDUP_CONFIRMED"
    OI_UNWINDING_CONFIRMED = "OI_UNWINDING_CONFIRMED"
    VOLUME_IMBALANCE_FLOW = "VOLUME_IMBALANCE_FLOW"
    POSITION_FLOW_CONFLICT = "POSITION_FLOW_CONFLICT"
    NO_PATTERN = "NO_PATTERN"


# ---------------------------------------------------------------------------
# Value helpers (deterministic)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _finite_or_none(value, name: str) -> None:
    if value is not None and (
        not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
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
# Raw input layer (canonical chain metrics — caller maps Day-20/21 outputs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstitutionalInput:
    """Canonical input to the institutional-like engine for one underlying.

    Fields mirror the Day-20 chain metric vocabulary (see the module plan for
    the mapping table from ``PositioningMetrics``/``FlowMetrics``); every
    measurement is ``float | None`` — ``None`` is genuinely missing (never
    coerced to 0.0), a measured 0.0 is a legitimate zero.  OI/volume are in
    contracts; delta/vega shifts are signed notional.  ``level_classifications``
    are the typed Day-21 rows (kind SUPPORT/RESISTANCE with strength); only
    proximate classified rows are used.  Timestamps are explicit and genuinely
    timezone-aware; ``quality`` is the preserved Day-12 assessment (``None``
    is allowed and yields a non-SUCCESS result, never a fabricated read).
    """

    underlying: str
    reference_timestamp: datetime
    provenance: Provenance
    expiry: str | None = None
    spot: float | None = None
    spot_change: float | None = None
    window_seconds: float | None = None
    net_call_oi_change: float | None = None
    net_put_oi_change: float | None = None
    total_call_oi: float | None = None
    total_put_oi: float | None = None
    call_volume: float | None = None
    put_volume: float | None = None
    call_delta_shift: float | None = None
    put_delta_shift: float | None = None
    vega_shift_net: float | None = None
    level_classifications: tuple[LevelClassification, ...] = ()
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        _finite_or_none(self.spot, "spot")
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive when present")
        _finite_or_none(self.spot_change, "spot_change")
        if self.window_seconds is not None and (
            not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(self.window_seconds) or self.window_seconds <= 0
        ):
            raise ValueError("window_seconds must be a finite positive number or None")
        # ΔOI shifts are signed; OI levels and volumes are non-negative.
        for name in ("net_call_oi_change", "net_put_oi_change",
                     "call_delta_shift", "put_delta_shift", "vega_shift_net"):
            _finite_or_none(getattr(self, name), name)
        for name in ("total_call_oi", "total_put_oi", "call_volume", "put_volume"):
            _non_negative_or_none(getattr(self, name), name)
        if not isinstance(self.level_classifications, tuple) or not all(
            isinstance(l, LevelClassification) for l in self.level_classifications
        ):
            raise ValueError(
                "level_classifications must be a tuple of Day-21 LevelClassification"
            )
        if not _aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Day-9 Provenance")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")


# ---------------------------------------------------------------------------
# Derived context layer
# ---------------------------------------------------------------------------


class _Context:
    """Deterministic derived context (all ``None`` when not computable)."""

    __slots__ = ("net", "flow", "delta_shift", "total_volume", "imbalance",
                 "any_activity")

    def __init__(self, inp: InstitutionalInput) -> None:
        cd = inp.net_call_oi_change
        pd = inp.net_put_oi_change
        cv = inp.call_volume
        pv = inp.put_volume
        self.net = cd + pd if (cd is not None and pd is not None) else None
        self.flow = cd - pd if (cd is not None and pd is not None) else None
        cds, pds = inp.call_delta_shift, inp.put_delta_shift
        self.delta_shift = (cds + pds) if (cds is not None and pds is not None) else None
        self.total_volume = (cv + pv) if (cv is not None and pv is not None) else None
        self.imbalance = None
        if cv is not None and pv is not None and cv + pv > 0.0:
            self.imbalance = (cv - pv) / (cv + pv)
        self.any_activity = any(
            v is not None
            for v in (cd, pd, inp.total_call_oi, inp.total_put_oi,
                      cv, pv, cds, pds, inp.vega_shift_net)
        )


def _proximate_levels(inp: InstitutionalInput) -> tuple[LevelClassification, ...]:
    """Classified (SUPPORT/RESISTANCE) levels with a strength whose strike is
    within LEVEL_PROXIMITY_FRACTION of spot — deterministic, spot > 0."""
    if inp.spot is None or inp.spot <= 0:
        return ()
    out = []
    for lvl in inp.level_classifications:
        if lvl.kind not in (LevelKind.SUPPORT, LevelKind.RESISTANCE):
            continue
        if lvl.strength is None:
            continue
        if abs(lvl.strike - inp.spot) / inp.spot <= LEVEL_PROXIMITY_FRACTION:
            out.append(lvl)
    out.sort(key=lambda l: l.strike)
    return tuple(out)


def _conflicted_strength(levels: tuple[LevelClassification, ...]) -> float | None:
    """Max strength of proximate CONFLICTED_INTERACTION levels (None if none)."""
    strengths = [l.strength for l in levels
                 if l.state is LevelState.CONFLICTED_INTERACTION
                 and l.strength is not None]
    return max(strengths) if strengths else None


def _has_directional_price(price) -> bool:
    return price is not None and price != 0.0


def _sign(value: float) -> int:
    return 1 if value > 0 else -1


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None,
           message: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code,
                             message=message or code.value,
                             field=field)


def _ref(inp: InstitutionalInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"inst:{inp.underlying}:{scope}:{key}"


def _ev(inp: InstitutionalInput, key: str, value: float, unit: str | None,
        kind: EvidenceType = EvidenceType.MARKET_OBSERVATION) -> IntelligenceEvidence:
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


def _evidence_rows(inp: InstitutionalInput, ctx: _Context) -> list[IntelligenceEvidence]:
    """Deterministic present-value-only evidence rows (missing never enters).
    Level rows carry the level's measured strength (score) with a
    kind/strike-qualified reference."""
    out: list[IntelligenceEvidence] = []
    raw = [
        ("total_call_oi", inp.total_call_oi, "contracts"),
        ("total_put_oi", inp.total_put_oi, "contracts"),
        ("net_call_oi_change", inp.net_call_oi_change, "contracts"),
        ("net_put_oi_change", inp.net_put_oi_change, "contracts"),
        ("net_chain_oi_change", ctx.net, "contracts"),
        ("ce_pe_flow", ctx.flow, "contracts"),
        ("call_volume", inp.call_volume, "contracts"),
        ("put_volume", inp.put_volume, "contracts"),
        ("total_volume", ctx.total_volume, "contracts"),
        ("volume_imbalance", ctx.imbalance, None),
        ("net_delta_shift", ctx.delta_shift, None),
        ("vega_shift_net", inp.vega_shift_net, None),
        ("spot", inp.spot, "points"),
        ("spot_change", inp.spot_change, "points"),
    ]
    for key, value, unit in raw:
        if value is not None:
            out.append(_ev(inp, key, float(value), unit))
    for lvl in _proximate_levels(inp):
        out.append(_ev(
            inp,
            f"level_strength:{lvl.kind.value}:{lvl.strike:g}:{lvl.state.value}",
            float(lvl.strength),
            "score_0_1",
            EvidenceType.QUANT_DERIVED,
        ))
    return out


# ---------------------------------------------------------------------------
# Interpretation layer (deterministic cascade — one result per evaluation)
# ---------------------------------------------------------------------------


def evaluate_institutional(inp: InstitutionalInput) -> IntelligenceResult:
    """Evaluate one chain and return the authoritative Day-19
    :class:`IntelligenceResult` (exactly one per evaluation)."""
    ctx = _Context(inp)
    issues: list[IntelligenceIssue] = []
    status: IntelligenceStatus | None = None
    direction: IntelligenceDirection | None = None
    strength: float | None = None
    confidence: float | None = None
    observation: IntelligenceObservation | None = None
    evidence: list[IntelligenceEvidence] = []
    pattern: ActivityPattern | None = None
    price = inp.spot_change

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

    # -- usable evidence? ---------------------------------------------------
    has_levels = bool(_proximate_levels(inp))
    activity_present = any(
        v is not None
        for v in (inp.net_call_oi_change, inp.net_put_oi_change,
                  inp.call_volume, inp.put_volume)
    )
    if not ctx.any_activity and not has_levels:
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "chain"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return finish()

    evidence = _evidence_rows(inp, ctx)

    # -- missing quality ----------------------------------------------------
    if inp.quality is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return finish()

    # -- conflict (highest pattern priority; never forced a side) -----------
    if _has_directional_price(price):
        if ctx.delta_shift is not None and ctx.delta_shift != 0.0 \
                and _sign(ctx.delta_shift) != _sign(price):
            pattern = ActivityPattern.POSITION_FLOW_CONFLICT
            status = IntelligenceStatus.PARTIAL
            issues.append(_issue(
                IntelligenceIssueCode.CONFLICTING_DIRECTION, "net_delta_shift",
                "delta shift opposes price — conflicting evidence"))
            strength = min(abs(ctx.delta_shift) / DELTA_STRENGTH_REFERENCE, 1.0)
        elif inp.vega_shift_net is not None and inp.vega_shift_net != 0.0 \
                and _sign(inp.vega_shift_net) != _sign(price):
            pattern = ActivityPattern.POSITION_FLOW_CONFLICT
            status = IntelligenceStatus.PARTIAL
            issues.append(_issue(
                IntelligenceIssueCode.CONFLICTING_DIRECTION, "vega_shift_net",
                "net vega demand opposes price — conflicting evidence"))
            strength = min(abs(inp.vega_shift_net) / DELTA_STRENGTH_REFERENCE, 1.0)
        else:
            lvl_strength = _conflicted_strength(_proximate_levels(inp))
            if lvl_strength is not None:
                pattern = ActivityPattern.POSITION_FLOW_CONFLICT
                status = IntelligenceStatus.PARTIAL
                issues.append(_issue(
                    IntelligenceIssueCode.CONFLICTING_DIRECTION,
                    "level_interaction",
                    "price has broken through a proximate level — conflicting "
                    "evidence"))
                strength = lvl_strength
        if pattern is ActivityPattern.POSITION_FLOW_CONFLICT:
            direction = IntelligenceDirection.MIXED
            confidence = CONFIDENCE_CONFLICT
            observation = IntelligenceObservation(
                metric_name=pattern.value,
                value=float(strength if strength is not None else 0.0),
                unit="score_0_1",
            )
            return finish()

    price_dir = _has_directional_price(price)

    # -- usable OI but no price context --------------------------------------
    net = ctx.net
    if net is not None and price is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "spot_change"))
        confidence = CONFIDENCE_NO_PRICE
        observation = IntelligenceObservation(
            metric_name="net_chain_oi_change",
            value=float(net),
            unit="contracts",
        )
        return finish()

    # -- OI buildup / unwinding (scale-gated) --------------------------------
    if net is not None and price_dir:
        if net >= OI_ACTIVITY_FLOOR:
            pattern = ActivityPattern.OI_BUILDUP_CONFIRMED
            status = IntelligenceStatus.SUCCESS
            direction = (IntelligenceDirection.BULLISH if price > 0
                         else IntelligenceDirection.BEARISH)
            strength = min(net / OI_STRENGTH_REFERENCE, 1.0)
        elif net <= -OI_ACTIVITY_FLOOR:
            pattern = ActivityPattern.OI_UNWINDING_CONFIRMED
            status = IntelligenceStatus.SUCCESS
            direction = (IntelligenceDirection.BULLISH if price > 0
                         else IntelligenceDirection.BEARISH)
            strength = min(-net / OI_STRENGTH_REFERENCE, 1.0)
        if pattern is not None:
            volumes_present = (inp.call_volume is not None
                               or inp.put_volume is not None)
            confidence = (CONFIDENCE_FULL if volumes_present
                          else CONFIDENCE_SINGLE_SIDE)
            observation = IntelligenceObservation(
                metric_name=pattern.value,
                value=float(strength),
                unit="score_0_1",
            )
            return finish()

    # -- volume imbalance (aggressive-looking flow) --------------------------
    tv = ctx.total_volume
    im = ctx.imbalance
    if (tv is not None and tv >= VOLUME_ACTIVITY_FLOOR
            and im is not None and abs(im) >= IMBALANCE_THRESHOLD):
        if price_dir:
            if _sign(im) == _sign(price):
                pattern = ActivityPattern.VOLUME_IMBALANCE_FLOW
                status = IntelligenceStatus.SUCCESS
                direction = (IntelligenceDirection.BULLISH if im > 0
                             else IntelligenceDirection.BEARISH)
                strength = abs(im)
                confidence = CONFIDENCE_IMBALANCE
            else:
                pattern = ActivityPattern.VOLUME_IMBALANCE_FLOW
                status = IntelligenceStatus.PARTIAL
                issues.append(_issue(
                    IntelligenceIssueCode.CONFLICTING_DIRECTION,
                    "volume_imbalance_vs_price",
                    "volume imbalance opposes price — conflicting evidence"))
                direction = IntelligenceDirection.MIXED
                strength = abs(im)
                confidence = CONFIDENCE_CONFLICT
            observation = IntelligenceObservation(
                metric_name=pattern.value,
                value=float(abs(im)),
                unit="ratio_0_1",
            )
            return finish()
        # price missing: the aggressive-looking flow is measurable but its
        # reading needs price — PARTIAL, never a fabricated direction
        if price is None:
            status = IntelligenceStatus.PARTIAL
            issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                                 "spot_change"))
            observation = IntelligenceObservation(
                metric_name=ActivityPattern.VOLUME_IMBALANCE_FLOW.value,
                value=float(abs(im)),
                unit="ratio_0_1",
            )
            return finish()

    # -- incomplete OI legs (nothing stronger fired) --------------------------
    cd = inp.net_call_oi_change
    pd = inp.net_put_oi_change
    if (cd is not None or pd is not None) and net is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(
            IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
            "net_put_oi_change" if pd is None else "net_call_oi_change"))
        return finish()

    # -- context without an activity series (standing OI / levels only) -----
    if not activity_present:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "chain_oi_change",
                             "no chain OI/volume change series — static "
                             "structure alone cannot support an activity read"))
        return finish()

    # -- measured activity with no institutional-like signature --------------
    pattern = ActivityPattern.NO_PATTERN
    status = IntelligenceStatus.SUCCESS
    direction = IntelligenceDirection.NEUTRAL
    strength = 0.0
    volumes_present = (inp.call_volume is not None or inp.put_volume is not None)
    confidence = (CONFIDENCE_FULL if volumes_present
                  else (CONFIDENCE_SINGLE_SIDE if inp.spot_change is not None
                        else CONFIDENCE_NO_PRICE))
    observation = IntelligenceObservation(
        metric_name=pattern.value,
        value=0.0,
        unit="score_0_1",
    )
    return finish()
