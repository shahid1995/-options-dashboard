"""Day 25 — Trap Detection Intelligence.

Deterministic, broker-neutral trap-candidate detection on the Day-19
Intelligence Contract, consuming only typed evidence available through the
existing engines::

    price attempt (caller spot_change)
        + family directional reads (Days 20-23)
        -> opposing / agreeing evidence-family evaluation
        -> trap-candidate classification
        -> Day-19 IntelligenceResult

Vocabulary is **trap candidate / trap-like condition** — never certainty,
never participant/institutional intent, never hidden flow, never a claim
about who is on the other side.  One :class:`IntelligenceResult` per
evaluation.

Evidence-family model
---------------------
Raw fields that derive from the same measurement are never counted as
independent confirmations.  Each family contributes at most ONE directional
read:

* PRICE — caller ``spot_change`` sign (+1 bullish attempt / -1 bearish
  attempt / 0 measured flat; missing = no attempt).
* POSITIONING — Day-20 ``PositioningClassification`` via the public
  ``classification_direction`` map (UNCLASSIFIED = no read).
* FLOW — Day-20 derived ``PriceFlowRelation`` (CONFIRM / DIVERGE /
  NO_SIGNAL); DIVERGE opposes the attempt, CONFIRM agrees.
* LEVEL — Day-21 ``LevelClassification`` rows; only proximate classified
  rows with strength are used; a trap-opposing read requires the
  Day-21/23 kind-aware ``CONFLICTED_INTERACTION`` semantics (conflicted
  SUPPORT opposes a rising attempt — a support breakdown; conflicted
  RESISTANCE opposes a falling attempt — a resistance breakout).  Level
  existence alone never creates a trap; ``APPROACHING`` never confirms
  interaction (Day-21 remediation).
* INSTITUTIONAL_LIKE — Day-22 result direction (BULLISH/BEARISH) and
  measured strength; MIXED carries NO directional implication (Day-23
  correction).
* REGIME — Day-23 result direction (BULLISH/BEARISH) and label (evidence);
  MIXED carries NO directional implication.

``MIXED``/``UNKNOWN``/``NO_SIGNAL`` never count as either side; missing
stays missing (never opposing, never agreeing, never zero).

Classification cascade
----------------------
1. No evidence at all -> UNAVAILABLE + MISSING_EVIDENCE (+ MISSING_QUALITY
   when quality absent).
2. quality None -> PARTIAL + MISSING_QUALITY; Day-12 INSUFFICIENT ->
   PARTIAL + INSUFFICIENT_QUALITY.
3. ``spot_change is None`` -> PARTIAL + MISSING_REQUIRED_INPUT(spot_change)
   — a trap cannot be evaluated without a directional move.
4. ``spot_change == 0.0`` (measured flat) -> SUCCESS NO_TRAP, strength 0.0.
5. Attempt + no directional family reads -> PARTIAL +
   MISSING_REQUIRED_INPUT(directional_evidence) — insufficient evidence is
   never NO_TRAP by convenience.
6. >= 1 opposing family -> SUCCESS trap candidate; label by the opposing
   set: {FLOW} -> FLOW_PRICE_TRAP; {LEVEL} -> FAILED_BREAKOUT (bullish
   attempt) / FAILED_BREAKDOWN (bearish attempt); otherwise ->
   BULL_TRAP_CANDIDATE / BEAR_TRAP_CANDIDATE.  Result direction = the
   OPPOSITE of the attempted move (a bullish attempt contradicted by
   opposing evidence is interpreted bearishly, and vice-versa).
7. No opposing + >= 1 agreeing -> SUCCESS NO_TRAP (valid sufficient
   evidence, no contradiction).

Strength = min(sum of opposing family strengths, 1.0) — the amount of
independent contradictory evidence, never the raw field count.  Confidence
is a completeness table (opposing+agreeing 0.80; opposing-only 0.70;
clean agree 0.90; flat 0.90) — never equal to strength.  Day-12 quality is
preserved (identity) and gated; Day-9 provenance preserved verbatim;
horizon EXPIRY (chain-scoped, mirroring Days 20-24).

Deterministic and pure: no wall clock, randomness, network, filesystem,
database, broker or services access; no mutable global state; all
timestamps caller-supplied and timezone-aware.
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
    RegimeLabel,
    TimeHorizon,
)
from app.intelligence.flow import PriceFlowRelation
from app.intelligence.levels import LevelClassification, LevelKind, LevelState
from app.intelligence.positioning import (
    PositioningClassification,
    classification_direction,
)

# ---------------------------------------------------------------------------
# Identity / versioning / documented policy constants
# ---------------------------------------------------------------------------

CALCULATION_ID = "intelligence.trap_detection.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Level proximity fraction (mirrors the Day-23 documented constant).
LEVEL_PROXIMITY_FRACTION = 0.10

#: Documented label-level family strengths (one independent read per family).
FAMILY_STRENGTH_POSITIONING = 0.5
FAMILY_STRENGTH_FLOW = 0.5
FAMILY_STRENGTH_LABEL_LEVEL = 0.5   # institutional fallback when no strength
FAMILY_STRENGTH_REGIME = 0.5

#: Documented confidence table (completeness-based; never strength).
CONFIDENCE_TRAP_FULL = 0.80            # opposing + agreeing both observed
CONFIDENCE_TRAP_OPPOSING_ONLY = 0.70   # opposing observed, agreement missing
CONFIDENCE_NO_TRAP = 0.90              # price + agreeing, no opposing
CONFIDENCE_FLAT = 0.90                 # measured flat price


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class TrapClassification(str, Enum):
    """Deterministic trap-candidate vocabulary (candidate, never certainty)."""

    BULL_TRAP_CANDIDATE = "BULL_TRAP_CANDIDATE"
    BEAR_TRAP_CANDIDATE = "BEAR_TRAP_CANDIDATE"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    FAILED_BREAKDOWN = "FAILED_BREAKDOWN"
    FLOW_PRICE_TRAP = "FLOW_PRICE_TRAP"
    NO_TRAP = "NO_TRAP"


# ---------------------------------------------------------------------------
# Value helpers (deterministic)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _finite_or_none(value, name: str) -> None:
    if value is not None and (
        not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number or None")


def _aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _directional(value: IntelligenceDirection | None) -> bool:
    """A direction with an actual implication (MIXED/NEUTRAL/UNKNOWN do not)."""
    return value in (IntelligenceDirection.BULLISH, IntelligenceDirection.BEARISH)


def _opposes(direction: IntelligenceDirection, price_dir: int) -> bool:
    return (direction is IntelligenceDirection.BULLISH and price_dir < 0) or (
        direction is IntelligenceDirection.BEARISH and price_dir > 0)


def _agrees(direction: IntelligenceDirection, price_dir: int) -> bool:
    return (direction is IntelligenceDirection.BULLISH and price_dir > 0) or (
        direction is IntelligenceDirection.BEARISH and price_dir < 0)


# ---------------------------------------------------------------------------
# Raw input layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrapInput:
    """Canonical input to the trap engine for one underlying chain.

    Family inputs are caller-supplied from the existing engines' typed
    outputs (see the module plan for the mapping table).  ``spot_change`` is
    the explicit signed price move (``None`` = missing, never coerced);
    ``positioning`` is the Day-20 classification; ``price_flow_relation`` is
    the Day-20 derived relation; ``level_classifications`` are the typed
    Day-21 rows; ``institutional_direction``/``institutional_strength`` come
    from the Day-22 result (MIXED carries no implication); ``regime_label``/
    ``regime_direction`` come from the Day-23 result.  ``quality`` is the
    preserved Day-12 assessment (``None`` is allowed and yields a non-SUCCESS
    result).  Timestamps are explicit and genuinely timezone-aware.
    """

    underlying: str
    reference_timestamp: datetime
    provenance: Provenance
    expiry: str | None = None
    spot: float | None = None
    spot_change: float | None = None
    positioning: PositioningClassification | None = None
    price_flow_relation: PriceFlowRelation | None = None
    level_classifications: tuple[LevelClassification, ...] = ()
    institutional_direction: IntelligenceDirection | None = None
    institutional_strength: float | None = None
    regime_label: RegimeLabel | None = None
    regime_direction: IntelligenceDirection | None = None
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not _aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        _finite_or_none(self.spot, "spot")
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive when present")
        _finite_or_none(self.spot_change, "spot_change")
        if self.positioning is not None and not isinstance(
            self.positioning, PositioningClassification
        ):
            raise ValueError("positioning must be a PositioningClassification or None")
        if self.price_flow_relation is not None and not isinstance(
            self.price_flow_relation, PriceFlowRelation
        ):
            raise ValueError("price_flow_relation must be a PriceFlowRelation or None")
        if not isinstance(self.level_classifications, tuple) or not all(
            isinstance(l, LevelClassification)
            for l in self.level_classifications
        ):
            raise ValueError(
                "level_classifications must be a tuple of Day-21 LevelClassification")
        if self.institutional_direction is not None and not isinstance(
            self.institutional_direction, IntelligenceDirection
        ):
            raise ValueError(
                "institutional_direction must be an IntelligenceDirection or None")
        _finite_or_none(self.institutional_strength, "institutional_strength")
        if self.institutional_strength is not None and not (
            0.0 <= self.institutional_strength <= 1.0
        ):
            raise ValueError("institutional_strength must be in [0, 1] or None")
        if self.regime_label is not None and not isinstance(self.regime_label, RegimeLabel):
            raise ValueError("regime_label must be a RegimeLabel or None")
        if self.regime_direction is not None and not isinstance(
            self.regime_direction, IntelligenceDirection
        ):
            raise ValueError("regime_direction must be an IntelligenceDirection or None")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Day-9 Provenance")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")


# ---------------------------------------------------------------------------
# Family read layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FamilyRead:
    """One independent family directional read (never double-counted).

    ``present`` is True when the caller supplied a usable input for the
    family (even when it carries no directional read); ``direction`` is the
    deterministic read (None = no directional implication); ``strength`` is
    the documented family strength contribution (0.0 when no read).
    """

    key: str            # evidence label, e.g. "positioning:SHORT_BUILDUP"
    present: bool       # caller supplied a usable family input
    direction: IntelligenceDirection | None  # None = no directional read
    strength: float     # documented family strength (0.0 when no read)


def _positioning_read(inp: TrapInput) -> _FamilyRead:
    if inp.positioning is None:
        return _FamilyRead("positioning:missing", False, None, 0.0)
    direction = classification_direction(inp.positioning)
    return _FamilyRead(
        f"positioning:{inp.positioning.value}", True, direction,
        FAMILY_STRENGTH_POSITIONING if direction is not None else 0.0,
    )


def _flow_read(inp: TrapInput, price_dir: int | None) -> _FamilyRead:
    if inp.price_flow_relation is None:
        return _FamilyRead("flow:missing", False, None, 0.0)
    if price_dir is None:
        # no price direction => the relation cannot form a directional read
        return _FamilyRead(
            f"flow:{inp.price_flow_relation.value}", True, None, 0.0)
    if inp.price_flow_relation is PriceFlowRelation.NO_SIGNAL:
        return _FamilyRead("flow:NO_SIGNAL", True, None, 0.0)
    # DIVERGE opposes the attempt; CONFIRM agrees with it.
    if inp.price_flow_relation is PriceFlowRelation.DIVERGE:
        direction = (IntelligenceDirection.BEARISH if price_dir > 0
                     else IntelligenceDirection.BULLISH)
        return _FamilyRead("flow:DIVERGE", True, direction, FAMILY_STRENGTH_FLOW)
    return _FamilyRead("flow:CONFIRM", True,
                       (IntelligenceDirection.BULLISH if price_dir > 0
                        else IntelligenceDirection.BEARISH),
                       FAMILY_STRENGTH_FLOW)


def _proximate_classified(inp: TrapInput, spot: float | None) -> \
        tuple[LevelClassification, ...]:
    """Classified SUPPORT/RESISTANCE rows (with strength) proximate to spot,
    by strike (mirrors the Day-23 proximity convention)."""
    if spot is None or spot <= 0:
        return ()
    out = []
    for lvl in inp.level_classifications:
        if lvl.kind not in (LevelKind.SUPPORT, LevelKind.RESISTANCE):
            continue
        if lvl.strength is None:
            continue
        if abs(lvl.strike - spot) / spot <= LEVEL_PROXIMITY_FRACTION:
            out.append(lvl)
    out.sort(key=lambda l: l.strike)
    return tuple(out)


def _proximate_conflicted(inp: TrapInput, spot: float | None) -> \
        tuple[LevelClassification, ...]:
    return tuple(l for l in _proximate_classified(inp, spot)
                 if l.state is LevelState.CONFLICTED_INTERACTION)


def _level_read(inp: TrapInput, price_dir: int | None,
                spot: float | None) -> _FamilyRead:
    classified = _proximate_classified(inp, spot)
    if not classified:
        return _FamilyRead("level:none", False, None, 0.0)
    conflicted = [l for l in classified
                  if l.state is LevelState.CONFLICTED_INTERACTION]
    if price_dir is not None:
        for lvl in conflicted:
            # Day-21/23 kind-aware semantics: conflicted SUPPORT implies a
            # bearish breakdown (opposes a rising attempt); conflicted
            # RESISTANCE implies a bullish breakout (opposes a falling
            # attempt).  Consistent conflicts never form a trap read.
            if lvl.kind is LevelKind.SUPPORT and price_dir > 0:
                return _FamilyRead(
                    f"level:{lvl.kind.value}:{lvl.strike:g}:{lvl.state.value}",
                    True, IntelligenceDirection.BEARISH, lvl.strength)
            if lvl.kind is LevelKind.RESISTANCE and price_dir < 0:
                return _FamilyRead(
                    f"level:{lvl.kind.value}:{lvl.strike:g}:{lvl.state.value}",
                    True, IntelligenceDirection.BULLISH, lvl.strength)
    if conflicted:
        return _FamilyRead(
            f"level:{conflicted[0].kind.value}:{conflicted[0].strike:g}:"
            f"{conflicted[0].state.value}", True, None, 0.0)
    return _FamilyRead("level:none", False, None, 0.0)


def _institutional_read(inp: TrapInput) -> _FamilyRead:
    if inp.institutional_direction is None:
        return _FamilyRead("institutional:missing", False, None, 0.0)
    direction = (inp.institutional_direction
                 if _directional(inp.institutional_direction) else None)
    strength = (inp.institutional_strength
                if inp.institutional_strength is not None
                else FAMILY_STRENGTH_LABEL_LEVEL)
    return _FamilyRead(
        f"institutional:{inp.institutional_direction.value}", True, direction,
        strength if direction is not None else 0.0,
    )


def _regime_read(inp: TrapInput) -> _FamilyRead:
    if inp.regime_direction is None:
        return _FamilyRead("regime:missing", False, None, 0.0)
    direction = (inp.regime_direction
                 if _directional(inp.regime_direction) else None)
    label = inp.regime_label.value if inp.regime_label is not None else "UNKNOWN"
    return _FamilyRead(
        f"regime:{label}", True, direction,
        FAMILY_STRENGTH_REGIME if direction is not None else 0.0,
    )


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None,
           message: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code,
                             message=message or code.value,
                             field=field)


def _ref(inp: TrapInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"trap:{inp.underlying}:{scope}:{key}"


def _ev(inp: TrapInput, key: str, value: float, unit: str | None,
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


# ---------------------------------------------------------------------------
# Interpretation layer
# ---------------------------------------------------------------------------


def _finish_result(inp: TrapInput, *, status: IntelligenceStatus,
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


def evaluate_traps(inp: TrapInput) -> IntelligenceResult:
    """Evaluate one underlying and return the authoritative Day-19
    :class:`IntelligenceResult` (exactly one per evaluation)."""
    issues: list[IntelligenceIssue] = []
    evidence: list[IntelligenceEvidence] = []

    price_dir = None
    if inp.spot_change is not None:
        price_dir = 0 if inp.spot_change == 0.0 else (1 if inp.spot_change > 0 else -1)

    family_inputs_present = any((
        inp.positioning is not None,
        inp.price_flow_relation is not None,
        bool(inp.level_classifications),
        inp.institutional_direction is not None,
        inp.regime_direction is not None,
    ))

    # -- usable evidence? ---------------------------------------------------
    if price_dir is None and not family_inputs_present:
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "chain"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return _finish_result(inp, status=IntelligenceStatus.UNAVAILABLE,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=[], issues=issues)

    # -- family reads (computed before gating so PARTIAL paths carry
    #    evidence — the Day-19 contract requires it) ------------------------
    reads = [
        _positioning_read(inp),
        _flow_read(inp, price_dir),
        _level_read(inp, price_dir, inp.spot),
        _institutional_read(inp),
        _regime_read(inp),
    ]
    opposing: list[_FamilyRead] = []
    agreeing: list[_FamilyRead] = []
    if price_dir is not None and price_dir != 0:
        for read in reads:
            if read.direction is None:
                continue
            if _opposes(read.direction, price_dir):
                opposing.append(read)
            elif _agrees(read.direction, price_dir):
                agreeing.append(read)

    for read in reads:
        if read.direction is not None:
            side = "opposing" if read in opposing else "agreeing"
            evidence.append(_ev(inp, f"{side}:{read.key}", float(read.strength),
                                "score_0_1", EvidenceType.QUANT_DERIVED))
        elif read.present:
            evidence.append(_ev(inp, f"read:{read.key}", 1.0, "present",
                                EvidenceType.QUANT_DERIVED))
    if price_dir is not None:
        evidence.append(_ev(inp, "price_attempt", float(price_dir), "attempt_sign"))
    if inp.spot_change is not None:
        evidence.append(_ev(inp, "spot_change", float(inp.spot_change), "points"))
    if opposing or agreeing:
        evidence.append(_ev(inp, "opposing_family_count",
                            float(len(opposing)), "families",
                            EvidenceType.QUANT_DERIVED))
        evidence.append(_ev(inp, "agreeing_family_count",
                            float(len(agreeing)), "families",
                            EvidenceType.QUANT_DERIVED))

    # -- quality gating -----------------------------------------------------
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

    # -- price direction required for any trap evaluation -------------------
    if price_dir is None:
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "spot_change",
                             "a directional move is required to evaluate a trap"))
        return _finish_result(inp, status=IntelligenceStatus.PARTIAL,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=evidence, issues=issues)

    # -- measured flat price (legitimate zero, not missing) -----------------
    if price_dir == 0:
        return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                              direction=IntelligenceDirection.NEUTRAL,
                              strength=0.0, confidence=CONFIDENCE_FLAT,
                              observation=IntelligenceObservation(
                                  metric_name=TrapClassification.NO_TRAP.value,
                                  value=0.0, unit="score_0_1"),
                              evidence=evidence, issues=issues)

    # -- insufficient directional evidence (never NO_TRAP by convenience) ---
    if not opposing and not agreeing:
        issues.append(_issue(IntelligenceIssueCode.MISSING_REQUIRED_INPUT,
                             "directional_evidence",
                             "no directional family read is available"))
        return _finish_result(inp, status=IntelligenceStatus.PARTIAL,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=evidence, issues=issues)

    # -- clean read: price + agreeing, no opposing --------------------------
    if not opposing:
        return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                              direction=IntelligenceDirection.NEUTRAL,
                              strength=0.0, confidence=CONFIDENCE_NO_TRAP,
                              observation=IntelligenceObservation(
                                  metric_name=TrapClassification.NO_TRAP.value,
                                  value=0.0, unit="score_0_1"),
                              evidence=evidence, issues=issues)

    # -- trap candidate (>= 1 independent opposing family) ------------------
    opposing_sum = min(sum(r.strength for r in opposing), 1.0)
    if opposing_sum <= 0.0:
        # measured-zero opposing reads: the family was present (its 0.0
        # evidence row proves it was not missing) but carries no magnitude.
        # The Day-19 contract requires positive strength for a directional
        # claim, so a zero-magnitude contradiction is a clean NO_TRAP.
        return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                              direction=IntelligenceDirection.NEUTRAL,
                              strength=0.0, confidence=CONFIDENCE_NO_TRAP,
                              observation=IntelligenceObservation(
                                  metric_name=TrapClassification.NO_TRAP.value,
                                  value=0.0, unit="score_0_1"),
                              evidence=evidence, issues=issues)
    confidence = (CONFIDENCE_TRAP_FULL if agreeing
                  else CONFIDENCE_TRAP_OPPOSING_ONLY)
    opposing_keys = {r.key.split(":")[0] for r in opposing}
    if opposing_keys == {"flow"}:
        label = TrapClassification.FLOW_PRICE_TRAP
    elif opposing_keys == {"level"}:
        label = (TrapClassification.FAILED_BREAKOUT if price_dir > 0
                 else TrapClassification.FAILED_BREAKDOWN)
    else:
        label = (TrapClassification.BULL_TRAP_CANDIDATE if price_dir > 0
                 else TrapClassification.BEAR_TRAP_CANDIDATE)
    trap_direction = (IntelligenceDirection.BEARISH if price_dir > 0
                      else IntelligenceDirection.BULLISH)
    return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                          direction=trap_direction,
                          strength=opposing_sum, confidence=confidence,
                          observation=IntelligenceObservation(
                              metric_name=label.value,
                              value=float(opposing_sum), unit="score_0_1"),
                          evidence=evidence, issues=issues)