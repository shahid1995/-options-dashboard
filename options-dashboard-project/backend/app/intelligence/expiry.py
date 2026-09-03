"""Day 24 — Expiry Intelligence + Market Event Detection.

Deterministic, broker-neutral expiry-context intelligence and observable
state-transition event detection on the Day-19 Intelligence Contract,
consuming only evidence available through the existing contracts::

    expiry timestamp + concentration rows (Day-20) + GEX (Day-17)
        + theta (Day-15) + typed evidence (Days 21-23)
        -> deterministic expiry context (proximity / concentration /
           gamma / pinning / time-decay)
        -> explicit prior+current state transitions (events)
        -> Day-19 IntelligenceResult(s)

Two evaluation surfaces:

* ``classify_expiry(inp)`` — typed expiry context (proximity, gamma context,
  pinning classification, time-decay context).
* ``evaluate_expiry(inp)`` — the Day-19 envelope for the expiry assessment
  (observation metric ``expiry_intelligence``; value = the documented
  proximity-strength component only — no opaque composite scores).
* ``evaluate_transitions(inp, previous=None)`` — event detection; an event is
  a **transition**, never a current state.  It fires only when BOTH prior and
  current observations are supplied and both endpoints are meaningful and
  different.  No previous observation => an explicit PARTIAL "initial state"
  condition — never a fabricated ``UNKNOWN -> X`` event.  Identical states =>
  no event.

Rules
-----
1. Concentration, GEX sign, theta and pinning are measurements / evidence
   patterns — never directional meaning, support/resistance, pin certainty or
   market-maker intent.  Results are ``direction=NEUTRAL``.
2. Missing stays ``None`` (never zero); a measured 0.0 stays a legitimate
   zero (measured-zero GEX => NEUTRAL gamma context).
3. Day-12 quality is preserved (identity) and gated; Day-9 provenance is
   preserved verbatim; quality is never recomputed.
4. ``signal_strength != confidence != quality``; horizon EXPIRY (chain-scoped,
   mirroring Days 20-23).
5. Deterministic and pure: no wall clock, randomness, network, filesystem,
   database, broker or services imports; no persistence; no event store.
6. GEX is consumed whole (Day-17 convention: signed net + source, never
   reimplemented); theta is consumed whole (Day-15 annualized convention);
   chain totals reuse the public Day-20 ``compute_metrics``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    RegimeLabel,
    TimeHorizon,
)
from app.intelligence.levels import LevelState
from app.intelligence.positioning import (
    PositioningClassification,
    PositioningInput,
    StrikePositioning,
    compute_metrics,
)
from app.intelligence.institutional import ActivityPattern

# ---------------------------------------------------------------------------
# Identity / versioning / documented policy constants
# ---------------------------------------------------------------------------

CALCULATION_ID = "intelligence.expiry_event.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Documented expiry-proximity thresholds (calendar days — the Day-14/18 time
#: convention: deterministic day arithmetic over explicit aware timestamps).
AT_EXPIRY_DAYS = 1.0
NEAR_EXPIRY_DAYS = 7.0

#: Pinning-pressure evidence-pattern thresholds (documented; never certainty).
PINNING_CONCENTRATION_FLOOR = 0.20
PINNING_SPOT_BAND = 0.02

#: Documented proximity-strength component (observation value source).
PROXIMITY_STRENGTH = {
    "AT_EXPIRY": 1.0,
    "NEAR": 0.6,
    "FAR": 0.3,
    "EXPIRED": 0.0,
    "UNKNOWN": 0.0,
}

#: Ordinal indices over the live proximity classes (for transition strength);
#: EXPIRED/UNKNOWN endpoints never fire a proximity transition.
_PROXIMITY_ORDINAL = {"FAR": 0, "NEAR": 1, "AT_EXPIRY": 2}

#: Ordinal indices over the live gamma contexts.
_GAMMA_ORDINAL = {"NEGATIVE": 0, "POSITIVE": 1}

#: Documented confidence table (completeness-based).
CONFIDENCE_FULL = 0.90
CONFIDENCE_PINNING = 0.85          # pinning candidate + GEX corroboration
CONFIDENCE_PINNING_NO_GEX = 0.70   # pinning candidate without GEX
CONFIDENCE_TRANSITION_PARTIAL = 0.70  # transition without expiry context


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class ExpiryProximity(str, Enum):
    """Deterministic expiry-proximity classes (calendar days)."""

    FAR = "FAR"
    NEAR = "NEAR"
    AT_EXPIRY = "AT_EXPIRY"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class GammaContext(str, Enum):
    """Chain GEX sign reading (Day-17 convention preserved; never
    reimplemented)."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"          # measured zero GEX
    UNSUPPORTED = "UNSUPPORTED"  # GEX missing


class TimeDecayContext(str, Enum):
    """Deterministic time-decay context (theta magnitude is never a
    directional prediction)."""

    ACCELERATING = "ACCELERATING"
    NORMAL = "NORMAL"
    UNSUPPORTED = "UNSUPPORTED"


class PinningClassification(str, Enum):
    """Derived pinning-pressure evidence pattern — NEVER certainty, NEVER
    market-maker positioning, NEVER a direction."""

    PINNING_CANDIDATE = "PINNING_CANDIDATE"
    PINNING_EVIDENCE = "PINNING_EVIDENCE"
    PINNING_UNSUPPORTED = "PINNING_UNSUPPORTED"


class EventType(str, Enum):
    """Deterministic observable state-transition event types (ordered —
    emission follows this enum order).  An event is a transition, never a
    current state."""

    REGIME_TRANSITION = "REGIME_TRANSITION"
    POSITIONING_TRANSITION = "POSITIONING_TRANSITION"
    LEVEL_TRANSITION = "LEVEL_TRANSITION"
    INSTITUTIONAL_TRANSITION = "INSTITUTIONAL_TRANSITION"
    EXPIRY_PROXIMITY_TRANSITION = "EXPIRY_PROXIMITY_TRANSITION"
    GAMMA_CONTEXT_TRANSITION = "GAMMA_CONTEXT_TRANSITION"
    DIRECTIONAL_CONFLICT_TRANSITION = "DIRECTIONAL_CONFLICT_TRANSITION"


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


def _aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _is_meaningful_regime(label: RegimeLabel | None) -> bool:
    return label is not None and label is not RegimeLabel.UNKNOWN


def _is_meaningful_positioning(label: PositioningClassification | None) -> bool:
    return label is not None and label is not PositioningClassification.UNCLASSIFIED


def _is_meaningful_level_state(state: LevelState | None) -> bool:
    return state is not None and state is not LevelState.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Raw input layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpiryInput:
    """Canonical input to the expiry/event engine for one underlying chain.

    All measurements are caller-supplied from the existing contracts and
    ``float | None`` — ``None`` is genuinely missing (never coerced to 0.0), a
    measured 0.0 stays a legitimate zero.  ``expiry_timestamp`` /
    ``reference_timestamp`` are explicit and genuinely timezone-aware (the
    engine never reads the wall clock).  ``gex``/``gex_source`` follow the
    Day-17 convention (signed net GEX + explicit BROKER/MODEL source);
    ``theta_reference`` is the Day-15 annualized model theta; the typed
    evidence fields come from Days 21-23 outputs.  ``quality`` is the
    preserved Day-12 assessment (None is allowed and yields non-SUCCESS).
    """

    underlying: str
    reference_timestamp: datetime
    provenance: Provenance
    expiry: str | None = None
    expiry_timestamp: datetime | None = None
    spot: float | None = None
    window_seconds: float | None = None
    rows: tuple[StrikePositioning, ...] = ()
    gex: float | None = None
    gex_source: str | None = None
    theta_reference: float | None = None
    regime_label: RegimeLabel | None = None
    positioning: PositioningClassification | None = None
    level_state: LevelState | None = None
    institutional_pattern: ActivityPattern | None = None
    conflict: bool | None = None
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not _aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        if self.expiry_timestamp is not None and not _aware(self.expiry_timestamp):
            raise ValueError("expiry_timestamp must be genuinely timezone-aware")
        _finite_or_none(self.spot, "spot")
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive when present")
        if self.window_seconds is not None and (
            not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(self.window_seconds) or self.window_seconds <= 0
        ):
            raise ValueError("window_seconds must be a finite positive number or None")
        if not isinstance(self.rows, tuple) or not all(
            isinstance(r, StrikePositioning) for r in self.rows
        ):
            raise ValueError("rows must be a tuple of Day-20 StrikePositioning")
        _finite_or_none(self.gex, "gex")
        if self.gex_source is not None:
            _require_text(self.gex_source, "gex_source")
            if self.gex is None:
                raise ValueError("gex_source requires a gex value")
        _finite_or_none(self.theta_reference, "theta_reference")
        if self.regime_label is not None and not isinstance(self.regime_label, RegimeLabel):
            raise ValueError("regime_label must be a RegimeLabel or None")
        if self.positioning is not None and not isinstance(
            self.positioning, PositioningClassification
        ):
            raise ValueError("positioning must be a PositioningClassification or None")
        if self.level_state is not None and not isinstance(self.level_state, LevelState):
            raise ValueError("level_state must be a LevelState or None")
        if self.institutional_pattern is not None and not isinstance(
            self.institutional_pattern, ActivityPattern
        ):
            raise ValueError("institutional_pattern must be an ActivityPattern or None")
        if self.conflict is not None and not isinstance(self.conflict, bool):
            raise ValueError("conflict must be a bool or None")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Day-9 Provenance")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")


# ---------------------------------------------------------------------------
# Derived context layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpiryContext:
    """Typed expiry context (deterministic derived classifications)."""

    proximity: ExpiryProximity = ExpiryProximity.UNKNOWN
    gamma_context: GammaContext = GammaContext.UNSUPPORTED
    pinning: PinningClassification = PinningClassification.PINNING_UNSUPPORTED
    time_decay: TimeDecayContext = TimeDecayContext.UNSUPPORTED


def _time_remaining_days(inp: ExpiryInput) -> float | None:
    if inp.expiry_timestamp is None:
        return None
    return (inp.expiry_timestamp - inp.reference_timestamp).total_seconds() / 86400.0


def _proximity(inp: ExpiryInput) -> ExpiryProximity:
    days = _time_remaining_days(inp)
    if days is None:
        return ExpiryProximity.UNKNOWN
    if days < 0:
        return ExpiryProximity.EXPIRED
    if days <= AT_EXPIRY_DAYS:
        return ExpiryProximity.AT_EXPIRY
    if days <= NEAR_EXPIRY_DAYS:
        return ExpiryProximity.NEAR
    return ExpiryProximity.FAR


def _gamma_context(inp: ExpiryInput) -> GammaContext:
    if inp.gex is None:
        return GammaContext.UNSUPPORTED
    if inp.gex > 0:
        return GammaContext.POSITIVE
    if inp.gex < 0:
        return GammaContext.NEGATIVE
    return GammaContext.NEUTRAL  # measured zero


def _time_decay(inp: ExpiryInput, proximity: ExpiryProximity) -> TimeDecayContext:
    if inp.theta_reference is None:
        return TimeDecayContext.UNSUPPORTED
    if proximity is ExpiryProximity.AT_EXPIRY or proximity is ExpiryProximity.NEAR:
        return TimeDecayContext.ACCELERATING
    if proximity is ExpiryProximity.FAR:
        return TimeDecayContext.NORMAL
    return TimeDecayContext.UNSUPPORTED


def _top_strike(rows: tuple[StrikePositioning, ...]) -> tuple[float, float] | None:
    """Dominant single-side OI strike (measurement; ties -> lower strike,
    mirroring the Day-20 tie convention)."""
    best = None
    best_value = None
    for r in rows:
        value = None
        if r.call_oi is not None:
            value = r.call_oi
        if r.put_oi is not None and (value is None or r.put_oi > value):
            value = r.put_oi
        if value is None:
            continue
        if best is None or value > best_value or (
            value == best_value and r.strike < best
        ):
            best = r.strike
            best_value = value
    return (best, best_value) if best is not None else None


def _concentration(inp: ExpiryInput) -> dict:
    """Deterministic chain concentration measurements (never directional)."""
    out: dict[str, float | None] = {
        "total_oi": None, "ce_share": None, "pe_share": None,
        "top_strike": None, "top_share": None, "spot_distance_top": None,
    }
    if not inp.rows:
        return out
    # chain totals via the public Day-20 compute_metrics (documented reuse)
    metrics = compute_metrics(PositioningInput(
        underlying=inp.underlying,
        expiry=inp.expiry,
        rows=inp.rows,
        reference_timestamp=inp.reference_timestamp,
        provenance=inp.provenance,
        quality=inp.quality,
    ))
    call_oi = metrics.total_call_oi
    put_oi = metrics.total_put_oi
    if call_oi is None and put_oi is None:
        return out
    total = (call_oi or 0.0) + (put_oi or 0.0)
    out["total_oi"] = total
    out["ce_share"] = call_oi / total if call_oi is not None else None
    out["pe_share"] = put_oi / total if put_oi is not None else None
    top = _top_strike(inp.rows)
    if top is not None:
        strike, value = top
        out["top_strike"] = strike
        out["top_share"] = value / total
        if inp.spot is not None and inp.spot > 0:
            out["spot_distance_top"] = abs(strike - inp.spot) / inp.spot
    return out


def _pinning(inp: ExpiryInput, proximity: ExpiryProximity,
             conc: dict) -> PinningClassification:
    """Deterministic pinning-pressure evidence pattern (never certainty).
    Candidate requires ALL of: live proximity; top_share >= floor; dominant
    strike within the spot band.  Evidence when only part of the pattern
    holds; unsupported otherwise.  Concentration alone is never a pin."""
    if proximity not in (ExpiryProximity.AT_EXPIRY, ExpiryProximity.NEAR):
        return PinningClassification.PINNING_UNSUPPORTED
    top_share = conc.get("top_share")
    spot_dist = conc.get("spot_distance_top")
    has_concentration = (
        top_share is not None and top_share >= PINNING_CONCENTRATION_FLOOR
    )
    has_spot_proximity = (
        spot_dist is not None and spot_dist <= PINNING_SPOT_BAND
    )
    if has_concentration and has_spot_proximity:
        return PinningClassification.PINNING_CANDIDATE
    if has_concentration or has_spot_proximity:
        return PinningClassification.PINNING_EVIDENCE
    return PinningClassification.PINNING_UNSUPPORTED


def classify_expiry(inp: ExpiryInput) -> ExpiryContext:
    """Deterministic typed expiry context (classifications only)."""
    proximity = _proximity(inp)
    return ExpiryContext(
        proximity=proximity,
        gamma_context=_gamma_context(inp),
        pinning=_pinning(inp, proximity, _concentration(inp)),
        time_decay=_time_decay(inp, proximity),
    )


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None,
           message: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code,
                             message=message or code.value,
                             field=field)


def _ref(inp: ExpiryInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"exp:{inp.underlying}:{scope}:{key}"


def _ev(inp: ExpiryInput, key: str, value: float, unit: str | None,
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


def _context_evidence(inp: ExpiryInput, prefix: str = "") -> list[IntelligenceEvidence]:
    """Deterministic present-value-only numeric context rows.  ``prefix`` is
    ``"prior:"`` for the previous-observation rows in transition results."""
    out: list[IntelligenceEvidence] = []
    proximity = _proximity(inp)
    days = _time_remaining_days(inp)
    conc = _concentration(inp)
    ctx = classify_expiry(inp)
    rows = [
        ("time_to_expiry_days", days, "days"),
        ("ce_share", conc.get("ce_share"), None),
        ("pe_share", conc.get("pe_share"), None),
        ("total_oi", conc.get("total_oi"), "contracts"),
        ("top_strike", conc.get("top_strike"), "points"),
        ("top_share", conc.get("top_share"), None),
        ("spot_distance_top", conc.get("spot_distance_top"), None),
        ("theta_reference", inp.theta_reference, "per_year"),
    ]
    for key, value, unit in rows:
        if value is not None:
            out.append(_ev(inp, f"{prefix}{key}", float(value), unit))
    if inp.gex is not None:
        source = inp.gex_source or "UNKNOWN"
        out.append(_ev(inp, f"{prefix}gex:{source}", float(inp.gex), "notional"))
    top_share = conc.get("top_share")
    if ctx.pinning is not PinningClassification.PINNING_UNSUPPORTED \
            and top_share is not None:
        out.append(_ev(inp, f"{prefix}pinning:{ctx.pinning.value}",
                       float(top_share), None,
                       EvidenceType.QUANT_DERIVED))
    # typed Day-21/22/23 state rows (presence evidence for transitions;
    # a state is never fabricated — rows exist only when supplied).
    state_rows = [
        ("regime", inp.regime_label),
        ("positioning", inp.positioning),
        ("level", inp.level_state),
        ("institutional", inp.institutional_pattern),
    ]
    for kind, value in state_rows:
        if value is not None:
            out.append(_ev(inp, f"{prefix}state:{kind}:{value.value}", 1.0,
                           None, EvidenceType.QUANT_DERIVED))
    if inp.conflict is not None:
        out.append(_ev(inp, f"{prefix}state:conflict:{str(inp.conflict).upper()}",
                       1.0, None, EvidenceType.QUANT_DERIVED))
    return out


# ---------------------------------------------------------------------------
# Interpretation layer
# ---------------------------------------------------------------------------


def _finish_result(inp: ExpiryInput, *, status: IntelligenceStatus,
                   direction: IntelligenceDirection | None,
                   strength: float | None, confidence: float | None,
                   observation: IntelligenceObservation | None,
                   evidence: list[IntelligenceEvidence],
                   issues: list[IntelligenceIssue]) -> IntelligenceResult:
    horizon = TimeHorizon.EXPIRY if status is IntelligenceStatus.SUCCESS else None
    return IntelligenceResult(
        calculation_id=CALCULATION_ID,
        status=status,
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


def evaluate_expiry(inp: ExpiryInput) -> IntelligenceResult:
    """Evaluate the expiry context and return the authoritative Day-19
    :class:`IntelligenceResult` (exactly one per evaluation)."""
    issues: list[IntelligenceIssue] = []
    ctx = classify_expiry(inp)
    evidence = _context_evidence(inp)

    has_evidence = any((
        inp.expiry_timestamp is not None,
        bool(inp.rows),
        inp.gex is not None,
        inp.theta_reference is not None,
    ))
    if not has_evidence:
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "chain"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return _finish_result(inp, status=IntelligenceStatus.UNAVAILABLE,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=[], issues=issues)

    if inp.quality is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return _finish_result(inp, status=IntelligenceStatus.PARTIAL,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=evidence, issues=issues)

    if inp.quality.quality_state is QualityState.INSUFFICIENT:
        issues.append(_issue(IntelligenceIssueCode.INSUFFICIENT_QUALITY,
                             "quality",
                             "input quality is below the interpretability floor"))
        return _finish_result(inp, status=IntelligenceStatus.PARTIAL,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=evidence, issues=issues)

    if inp.expiry_timestamp is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "expiry_timestamp"))
        return _finish_result(inp, status=IntelligenceStatus.PARTIAL,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=evidence, issues=issues)

    strength = PROXIMITY_STRENGTH.get(ctx.proximity.value, 0.0)
    if ctx.pinning is PinningClassification.PINNING_CANDIDATE:
        confidence = CONFIDENCE_PINNING if inp.gex is not None \
            else CONFIDENCE_PINNING_NO_GEX
    else:
        confidence = CONFIDENCE_FULL
    observation = IntelligenceObservation(
        metric_name="expiry_intelligence",
        value=float(strength),
        unit="score_0_1",
    )
    return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                          direction=IntelligenceDirection.NEUTRAL,
                          strength=strength, confidence=confidence,
                          observation=observation, evidence=evidence,
                          issues=issues)


# ---------------------------------------------------------------------------
# Event detection (transitions only — never states)
# ---------------------------------------------------------------------------


def _transition_candidates(inp: ExpiryInput,
                           previous: ExpiryInput) -> list[tuple[EventType, float]]:
    """Deterministic transition candidates over categories where both
    endpoints are supplied and meaningful.  Returns ``(event_type,
    strength)`` pairs in no particular order (sorted by the caller)."""
    out: list[tuple[EventType, float]] = []

    def _both(a, b) -> bool:
        return a is not None and b is not None

    if _is_meaningful_regime(previous.regime_label) \
            and _is_meaningful_regime(inp.regime_label) \
            and previous.regime_label != inp.regime_label:
        out.append((EventType.REGIME_TRANSITION, 1.0))
    if _is_meaningful_positioning(previous.positioning) \
            and _is_meaningful_positioning(inp.positioning) \
            and previous.positioning != inp.positioning:
        out.append((EventType.POSITIONING_TRANSITION, 1.0))
    if _is_meaningful_level_state(previous.level_state) \
            and _is_meaningful_level_state(inp.level_state) \
            and previous.level_state != inp.level_state:
        out.append((EventType.LEVEL_TRANSITION, 1.0))
    if _both(previous.institutional_pattern, inp.institutional_pattern) \
            and previous.institutional_pattern != inp.institutional_pattern:
        out.append((EventType.INSTITUTIONAL_TRANSITION, 1.0))

    p_prox = _proximity(previous)
    c_prox = _proximity(inp)
    if p_prox.value in _PROXIMITY_ORDINAL and c_prox.value in _PROXIMITY_ORDINAL \
            and p_prox is not c_prox:
        dist = abs(_PROXIMITY_ORDINAL[c_prox.value]
                   - _PROXIMITY_ORDINAL[p_prox.value])
        out.append((EventType.EXPIRY_PROXIMITY_TRANSITION, dist / 2.0))

    p_gamma = _gamma_context(previous)
    c_gamma = _gamma_context(inp)
    if p_gamma.value in _GAMMA_ORDINAL and c_gamma.value in _GAMMA_ORDINAL \
            and p_gamma is not c_gamma:
        dist = abs(_GAMMA_ORDINAL[c_gamma.value]
                   - _GAMMA_ORDINAL[p_gamma.value])
        out.append((EventType.GAMMA_CONTEXT_TRANSITION, dist / 1.0))

    if previous.conflict is not None and inp.conflict is not None \
            and previous.conflict != inp.conflict:
        out.append((EventType.DIRECTIONAL_CONFLICT_TRANSITION, 1.0))

    out.sort(key=lambda pair: list(EventType).index(pair[0]))
    return out


def evaluate_transitions(inp: ExpiryInput,
                         previous: ExpiryInput | None = None,
                         ) -> tuple[IntelligenceResult, ...]:
    """Detect observable state transitions between an explicit previous and
    the current observation.  Returns one result per fired event (ordered by
    :class:`EventType`), ``()`` when nothing transitioned, or an explicit
    PARTIAL "initial state" condition when no previous observation is
    supplied (a transition is never fabricated from an unknown prior)."""
    issues: list[IntelligenceIssue] = []
    evidence = _context_evidence(inp)

    # -- initial state: no prior observation --------------------------------
    if previous is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "previous",
                             "no prior observation — initial state, no "
                             "transition is inferred"))
        if not evidence:
            issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "chain"))
            return (_finish_result(inp, status=IntelligenceStatus.UNAVAILABLE,
                                   direction=None, strength=None,
                                   confidence=None, observation=None,
                                   evidence=[], issues=issues),)
        return (_finish_result(inp, status=IntelligenceStatus.PARTIAL,
                               direction=None, strength=None, confidence=None,
                               observation=None, evidence=evidence,
                               issues=issues),)

    # -- quality gating -----------------------------------------------------
    if inp.quality is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return (_finish_result(inp, status=IntelligenceStatus.PARTIAL,
                               direction=None, strength=None, confidence=None,
                               observation=None, evidence=evidence,
                               issues=issues),)
    if inp.quality.quality_state is QualityState.INSUFFICIENT:
        issues.append(_issue(IntelligenceIssueCode.INSUFFICIENT_QUALITY,
                             "quality",
                             "input quality is below the interpretability floor"))
        return (_finish_result(inp, status=IntelligenceStatus.PARTIAL,
                               direction=None, strength=None, confidence=None,
                               observation=None, evidence=evidence,
                               issues=issues),)

    candidates = _transition_candidates(inp, previous)
    if not candidates:
        return ()

    prior_evidence = _context_evidence(previous, prefix="prior:")
    context_complete = (
        _proximity(inp) is not ExpiryProximity.UNKNOWN
        and _proximity(previous) is not ExpiryProximity.UNKNOWN
    )
    results: list[IntelligenceResult] = []
    for event_type, strength in candidates:
        confidence = (CONFIDENCE_FULL if context_complete
                      else CONFIDENCE_TRANSITION_PARTIAL)
        observation = IntelligenceObservation(
            metric_name=event_type.value,
            value=float(strength),
            unit="score_0_1",
        )
        results.append(_finish_result(
            inp, status=IntelligenceStatus.SUCCESS,
            direction=IntelligenceDirection.NEUTRAL,
            strength=strength, confidence=confidence,
            observation=observation,
            evidence=prior_evidence + evidence, issues=[],
        ))
    return tuple(results)