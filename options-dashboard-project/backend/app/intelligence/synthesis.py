"""Day 26 — Intelligence Synthesis & Conflict Resolution.

Deterministic, broker-neutral synthesis of the per-family directional reads
produced by Days 20-25 into one transparent Day-19 ``IntelligenceResult``:

    Day-20 positioning / flow   (typed classifications + price relation)
    Day-21 level rows           (kind / state / strength)
    Day-22 institutional read   (direction + measured strength)
    Day-23 regime read          (label + direction)
    Day-25 trap pattern read    (candidate direction + strength)
        -> one directional read per evidence family (never majority vote)
        -> agreement / conflict / no-direction outcome
        -> Day-19 IntelligenceResult (bull / bear evidence exposed)

Semantic rules locked by the module tests:

1. Only BULLISH / BEARISH reads vote.  NEUTRAL, MIXED, UNKNOWN, NO_SIGNAL
   and label-only upstream reads never vote and never act as opposing
   evidence (Days 22-23 corrections).
2. No double counting of derived evidence:
   a. Day-22 institutional-like activity derives from the Day-20 OI-based
      positioning read.  Aligned (same-direction) reads form ONE vote at
      ``max(a, b)`` -- never the sum.  Opposing reads are a material
      divergence and both vote.
   b. The Day-25 trap classification is a pattern derived over the same
      family set.  A trap read duplicating any other vote of the same
      direction adds NO strength (recorded as ``context`` only); a
      unique-direction trap read votes.
3. Day-21 semantics preserved: only proximate (<= ``LEVEL_PROXIMITY_FRACTION``
   of spot) CONFLICTED_INTERACTION rows carry a directional implication
   (conflicted SUPPORT => bearish breakdown, conflicted RESISTANCE =>
   bullish breakout).  STATIC / APPROACHING / constructive rows are present
   measurements that never vote.
4. Missing != zero: a missing family input is absent; a measured-zero
   magnitude read is present but can never support a directional claim
   (the Day-19 contract requires positive strength for a directional
   claim).
5. Day-12 quality is preserved by identity and gates status; Day-9
   provenance is preserved verbatim; never recomputed.  signal_strength,
   confidence and quality stay separate.
6. Pure/deterministic: no wall clock, random, network, filesystem,
   database, broker or environment-dependent behavior.

Deterministic outcome model (documented constants):

    bull_total  = min(sum(independent bull vote strengths), 1.0)
    bear_total  = min(sum(independent bear vote strengths), 1.0)
    only bull votes  -> BULLISH_AGREEMENT / BULLISH  / bull_total
    only bear votes  -> BEARISH_AGREEMENT / BEARISH  / bear_total
    votes on both sides -> MATERIAL_CONFLICT / MIXED  /
        min(bull_total, bear_total)  (contested mass)
    reads present, no vote -> NO_DIRECTIONAL_EVIDENCE / UNKNOWN / 0.0

Confidence is a documented completeness/agreement table (never strength):
0.85 when >=2 independent winning votes, 0.75 for a single winning vote,
0.60 for material conflict, 0.70 when reads are present but nothing votes.
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
    MarketRegime,
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

CALCULATION_ID = "intelligence.synthesis.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Level proximity fraction (mirrors the Day-23/25 documented constant).
LEVEL_PROXIMITY_FRACTION = 0.10

#: Documented label-level family strengths (one independent read per family).
FAMILY_STRENGTH_POSITIONING = 0.5
FAMILY_STRENGTH_FLOW = 0.5
FAMILY_STRENGTH_INSTITUTIONAL = 0.5   # fallback when no measured strength
FAMILY_STRENGTH_REGIME = 0.5
FAMILY_STRENGTH_TRAP = 0.5            # fallback when no measured strength

#: Documented confidence table (completeness/agreement-based; never strength).
CONFIDENCE_AGREEMENT_MULTI = 0.85     # >= 2 independent winning votes
CONFIDENCE_AGREEMENT_SINGLE = 0.75    # one winning vote
CONFIDENCE_CONFLICT = 0.60            # material two-sided evidence
CONFIDENCE_NO_DIRECTION = 0.70        # reads present, none directional


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class SynthesisOutcome(str, Enum):
    """Deterministic synthesis outcome (mapped onto Day-19 direction)."""

    BULLISH_AGREEMENT = "BULLISH_AGREEMENT"
    BEARISH_AGREEMENT = "BEARISH_AGREEMENT"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    NO_DIRECTIONAL_EVIDENCE = "NO_DIRECTIONAL_EVIDENCE"


# ---------------------------------------------------------------------------
# Value helpers (deterministic — never wall-clock / random / IO)
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


# ---------------------------------------------------------------------------
# Raw input layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SynthesisInput:
    """Canonical input to the synthesis engine for one underlying chain.

    Family inputs are caller-supplied from the existing engines' typed
    outputs (see the module plan for the mapping table).  ``spot`` /
    ``spot_change`` provide the price context that converts the Day-20 flow
    relation and Day-21 level geometry into reads (never votes on their
    own).  ``positioning`` is the Day-20 classification;
    ``price_flow_relation`` is the Day-20 derived relation;
    ``level_classifications`` are the typed Day-21 rows;
    ``institutional_direction``/``institutional_strength`` come from the
    Day-22 result (MIXED carries no implication);
    ``regime_label``/``regime_direction`` come from the Day-23 result
    (label alone never votes); ``regime`` is the authoritative Day-23
    ``MarketRegime`` channel preserved through synthesis into
    ``IntelligenceResult.regime`` (never fabricated when absent);
    ``time_horizon`` is the caller-supplied authoritative horizon -- the
    synthesis layer never invents a horizon (a missing horizon yields
    PARTIAL + MISSING_HORIZON rather than a fabricated SUCCESS);
    ``trap_direction``/``trap_strength`` come from the Day-25 result
    (NO_TRAP / NEUTRAL never votes).  ``quality`` is the preserved Day-12
    assessment (``None`` is allowed and yields a non-SUCCESS result).
    Timestamps are explicit and genuinely timezone-aware.
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
    regime: MarketRegime | None = None
    time_horizon: TimeHorizon | None = None
    trap_direction: IntelligenceDirection | None = None
    trap_strength: float | None = None
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
        for name, value in (
            ("institutional_direction", self.institutional_direction),
            ("regime_direction", self.regime_direction),
            ("trap_direction", self.trap_direction),
        ):
            if value is not None and not isinstance(value, IntelligenceDirection):
                raise ValueError(f"{name} must be an IntelligenceDirection or None")
        for name, value in (
            ("institutional_strength", self.institutional_strength),
            ("trap_strength", self.trap_strength),
        ):
            _finite_or_none(value, name)
            if value is not None and not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0, 1] or None")
        if self.regime_label is not None and not isinstance(self.regime_label, RegimeLabel):
            raise ValueError("regime_label must be a RegimeLabel or None")
        if self.regime is not None and not isinstance(self.regime, MarketRegime):
            raise ValueError("regime must be a Day-23 MarketRegime or None")
        if self.regime is not None and self.regime_label is not None \
                and self.regime.label is not self.regime_label:
            raise ValueError(
                "regime.label must match regime_label when both are supplied")
        if self.time_horizon is not None and not isinstance(
            self.time_horizon, TimeHorizon
        ):
            raise ValueError("time_horizon must be a TimeHorizon or None")
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

    key: str            # evidence label, e.g. "positioning:LONG_BUILDUP"
    present: bool       # caller supplied a usable family input
    direction: IntelligenceDirection | None  # None = no directional read
    strength: float     # documented family strength (0.0 when no read)


def _positioning_read(inp: SynthesisInput) -> _FamilyRead:
    if inp.positioning is None:
        return _FamilyRead("positioning:missing", False, None, 0.0)
    direction = classification_direction(inp.positioning)
    return _FamilyRead(
        f"positioning:{inp.positioning.value}", True, direction,
        FAMILY_STRENGTH_POSITIONING if direction is not None else 0.0,
    )


def _flow_read(inp: SynthesisInput, price_dir: int | None) -> _FamilyRead:
    if inp.price_flow_relation is None:
        return _FamilyRead("flow:missing", False, None, 0.0)
    if price_dir is None:
        # no price direction => the relation cannot form a directional read
        return _FamilyRead(
            f"flow:{inp.price_flow_relation.value}", True, None, 0.0)
    if inp.price_flow_relation is PriceFlowRelation.NO_SIGNAL:
        return _FamilyRead("flow:NO_SIGNAL", True, None, 0.0)
    # CONFIRM agrees with the price direction; DIVERGE opposes it.
    if inp.price_flow_relation is PriceFlowRelation.DIVERGE:
        direction = (IntelligenceDirection.BEARISH if price_dir > 0
                     else IntelligenceDirection.BULLISH)
        return _FamilyRead("flow:DIVERGE", True, direction, FAMILY_STRENGTH_FLOW)
    return _FamilyRead("flow:CONFIRM", True,
                       (IntelligenceDirection.BULLISH if price_dir > 0
                        else IntelligenceDirection.BEARISH),
                       FAMILY_STRENGTH_FLOW)


def _proximate_classified(inp: SynthesisInput, spot: float | None) -> \
        tuple[LevelClassification, ...]:
    """Classified SUPPORT/RESISTANCE rows (with strength) proximate to spot,
    by strike (mirrors the Day-23/25 proximity convention)."""
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


def _level_read(inp: SynthesisInput) -> _FamilyRead:
    """Level family read (absolute semantics, never price-relative).

    A proximate CONFLICTED_INTERACTION row already encodes the break in the
    Day-21 state: conflicted SUPPORT => price broke down (BEARISH);
    conflicted RESISTANCE => price broke up (BULLISH).  The family votes
    once, from the strongest proximate conflicted row.  STATIC /
    APPROACHING / constructive proximate rows are a present measurement
    that never votes (Day-21 remediation: approach != interaction, level
    existence alone is not directional)."""
    classified = _proximate_classified(inp, inp.spot)
    if not classified:
        return _FamilyRead("level:none", False, None, 0.0)
    conflicted = [l for l in classified
                  if l.state is LevelState.CONFLICTED_INTERACTION]
    if conflicted:
        strongest = max(conflicted,
                        key=lambda l: l.strength if l.strength is not None else 0.0)
        direction = (IntelligenceDirection.BEARISH
                     if strongest.kind is LevelKind.SUPPORT
                     else IntelligenceDirection.BULLISH)
        return _FamilyRead(
            f"level:{strongest.kind.value}:{strongest.strike:g}:"
            f"{strongest.state.value}", True, direction,
            strongest.strength if strongest.strength is not None else 0.0)
    rep = classified[0]
    return _FamilyRead(
        f"level:{rep.kind.value}:{rep.strike:g}:{rep.state.value}", True, None, 0.0)


def _institutional_read(inp: SynthesisInput) -> _FamilyRead:
    if inp.institutional_direction is None:
        return _FamilyRead("institutional:missing", False, None, 0.0)
    direction = (inp.institutional_direction
                 if _directional(inp.institutional_direction) else None)
    strength = (inp.institutional_strength
                if inp.institutional_strength is not None
                else FAMILY_STRENGTH_INSTITUTIONAL)
    return _FamilyRead(
        f"institutional:{inp.institutional_direction.value}", True, direction,
        strength if direction is not None else 0.0,
    )


def _regime_read(inp: SynthesisInput) -> _FamilyRead:
    """Day-23 convention: regime_direction is the read; a label alone is an
    absent family.  Only an actual directional Day-23 read (BULLISH /
    BEARISH) votes -- RANGING (NEUTRAL) and volatility labels (UNKNOWN)
    are present measurements that never vote.  The authoritative label
    comes from the preserved Day-23 ``MarketRegime`` channel when supplied."""
    if inp.regime_direction is None:
        return _FamilyRead("regime:missing", False, None, 0.0)
    direction = (inp.regime_direction
                 if _directional(inp.regime_direction) else None)
    if inp.regime is not None:
        label = inp.regime.label.value
    elif inp.regime_label is not None:
        label = inp.regime_label.value
    else:
        label = "UNKNOWN"
    return _FamilyRead(
        f"regime:{label}", True, direction,
        FAMILY_STRENGTH_REGIME if direction is not None else 0.0,
    )


def _trap_read(inp: SynthesisInput) -> _FamilyRead:
    """Day-25 candidate pattern read: BULL_TRAP_CANDIDATE etc. carry a
    directional counter-context (BEARISH / BULLISH); NO_TRAP (NEUTRAL) and
    MIXED / UNKNOWN are present measurements that never vote.  The pattern
    is one family -- candidate context, never certainty, never an automatic
    override."""
    if inp.trap_direction is None:
        return _FamilyRead("trap:missing", False, None, 0.0)
    direction = (inp.trap_direction
                 if _directional(inp.trap_direction) else None)
    strength = (inp.trap_strength
                if inp.trap_strength is not None
                else FAMILY_STRENGTH_TRAP)
    return _FamilyRead(
        f"trap:{inp.trap_direction.value}", True, direction,
        strength if direction is not None else 0.0,
    )


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None,
           message: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code,
                             message=message or code.value,
                             field=field)


def _ref(inp: SynthesisInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"synthesis:{inp.underlying}:{scope}:{key}"


def _ev(inp: SynthesisInput, key: str, value: float, unit: str | None,
        kind: EvidenceType = EvidenceType.QUANT_DERIVED) -> IntelligenceEvidence:
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


@dataclass
class _Vote:
    """One counted/context candidate directional vote (internal)."""

    key: str
    direction: IntelligenceDirection
    strength: float
    counted: bool


def _finish_result(inp: SynthesisInput, *, status: IntelligenceStatus,
                   direction: IntelligenceDirection | None,
                   strength: float | None, confidence: float | None,
                   observation: IntelligenceObservation | None,
                   evidence: list[IntelligenceEvidence],
                   issues: list[IntelligenceIssue]) -> IntelligenceResult:
    # The synthesis layer never invents a horizon: a SUCCESS carries only a
    # caller-supplied time_horizon (the horizon gate guarantees it is not
    # None before any SUCCESS is returned).  The authoritative Day-23
    # MarketRegime channel is preserved through synthesis when supplied.
    horizon = inp.time_horizon if status is IntelligenceStatus.SUCCESS else None
    return IntelligenceResult(
        calculation_id=CALCULATION_ID,
        status=status,
        direction=direction,
        signal_strength=strength,
        confidence=confidence,
        time_horizon=horizon,
        observation=observation,
        evidence=tuple(evidence),
        regime=inp.regime,
        quality=inp.quality,
        provenance=inp.provenance,
        reference_timestamp=inp.reference_timestamp,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
        issues=tuple(issues),
    )


def evaluate_synthesis(inp: SynthesisInput) -> IntelligenceResult:
    """Synthesize one underlying and return the authoritative Day-19
    :class:`IntelligenceResult` (exactly one per evaluation)."""
    issues: list[IntelligenceIssue] = []
    evidence: list[IntelligenceEvidence] = []

    price_dir = None
    if inp.spot_change is not None:
        price_dir = 0 if inp.spot_change == 0.0 else (1 if inp.spot_change > 0 else -1)

    # -- family reads (computed before gating so PARTIAL paths carry
    #    evidence -- the Day-19 contract requires it) ------------------------
    reads = [
        _positioning_read(inp),
        _flow_read(inp, price_dir),
        _level_read(inp),
        _institutional_read(inp),
        _regime_read(inp),
        _trap_read(inp),
    ]
    reads_present = any(r.present for r in reads)

    # -- usable evidence? ---------------------------------------------------
    if not reads_present:
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "chain"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return _finish_result(inp, status=IntelligenceStatus.UNAVAILABLE,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=[], issues=issues)

    # -- candidate votes + correlation (never double-count derived reads) ----
    votes: list[_Vote] = []
    for read in reads:
        if read.direction is None or read.strength <= 0.0:
            continue
        votes.append(_Vote(read.key, read.direction, read.strength, True))

    # Same-OI alignment: Day-22 institutional derives from Day-20 positioning.
    positioning = next((v for v in votes
                        if v.key.startswith("positioning:")), None)
    institutional = next((v for v in votes
                          if v.key.startswith("institutional:")), None)
    if (positioning is not None and institutional is not None
            and positioning.direction is institutional.direction):
        positioning.strength = max(positioning.strength, institutional.strength)
        institutional.counted = False

    # Derived-pattern duplication: a trap read duplicating any other vote of
    # the same direction adds no strength (recorded as context only).
    trap = next((v for v in votes if v.key.startswith("trap:")), None)
    if trap is not None:
        duplicated = any(
            v.counted and v is not trap and v.direction is trap.direction
            for v in votes)
        if duplicated:
            trap.counted = False

    # -- evidence rows ------------------------------------------------------
    for read in reads:
        if read.direction is not None and read.strength > 0.0:
            vote = next(v for v in votes if v.key == read.key)
            if vote.counted:
                side = ("bull" if read.direction is IntelligenceDirection.BULLISH
                        else "bear")
                evidence.append(_ev(inp, f"{side}:{read.key}",
                                    float(vote.strength), "score_0_1"))
            else:
                evidence.append(_ev(inp, f"context:{read.key}",
                                    float(read.strength), "score_0_1"))
        elif read.present:
            evidence.append(_ev(inp, f"read:{read.key}", 1.0, "present"))

    bull_votes = [v for v in votes if v.counted
                  and v.direction is IntelligenceDirection.BULLISH]
    bear_votes = [v for v in votes if v.counted
                  and v.direction is IntelligenceDirection.BEARISH]
    bull_total = min(sum(v.strength for v in bull_votes), 1.0)
    bear_total = min(sum(v.strength for v in bear_votes), 1.0)
    if bull_votes or bear_votes:
        evidence.append(_ev(inp, "synthesis:bull_total", float(bull_total),
                            "score_0_1"))
        evidence.append(_ev(inp, "synthesis:bear_total", float(bear_total),
                            "score_0_1"))
        evidence.append(_ev(inp, "synthesis:net",
                            float(bull_total - bear_total), "score"))

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

    # -- time-horizon gate: never invent EXPIRY for the synthesis ------------
    # Day-19 SUCCESS requires a time_horizon; the synthesis layer has no
    # authoritative horizon of its own, so without a caller-supplied one the
    # interpretation stays PARTIAL (structured issue) instead of fabricating
    # a SUCCESS on an invented horizon.
    if inp.time_horizon is None:
        issues.append(_issue(
            IntelligenceIssueCode.MISSING_HORIZON, "time_horizon",
            "a caller-supplied time horizon is required for synthesis "
            "SUCCESS -- the engine never invents one"))
        return _finish_result(inp, status=IntelligenceStatus.PARTIAL,
                              direction=None, strength=None, confidence=None,
                              observation=None, evidence=evidence, issues=issues)

    # -- no directional vote across present reads (measured, never missing) --
    if not bull_votes and not bear_votes:
        return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                              direction=IntelligenceDirection.UNKNOWN,
                              strength=0.0, confidence=CONFIDENCE_NO_DIRECTION,
                              observation=IntelligenceObservation(
                                  metric_name=SynthesisOutcome.NO_DIRECTIONAL_EVIDENCE.value,
                                  value=0.0, unit="score_0_1"),
                              evidence=evidence, issues=issues)

    # -- material two-sided evidence: expose the conflict, never choose ------
    if bull_total > 0.0 and bear_total > 0.0:
        return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                              direction=IntelligenceDirection.MIXED,
                              strength=min(bull_total, bear_total),
                              confidence=CONFIDENCE_CONFLICT,
                              observation=IntelligenceObservation(
                                  metric_name=SynthesisOutcome.MATERIAL_CONFLICT.value,
                                  value=float(min(bull_total, bear_total)),
                                  unit="score_0_1"),
                              evidence=evidence, issues=issues)

    # -- one-sided agreement -------------------------------------------------
    if bull_votes:
        outcome = SynthesisOutcome.BULLISH_AGREEMENT
        direction = IntelligenceDirection.BULLISH
        strength = bull_total
        confidence = (CONFIDENCE_AGREEMENT_MULTI if len(bull_votes) >= 2
                      else CONFIDENCE_AGREEMENT_SINGLE)
    else:
        outcome = SynthesisOutcome.BEARISH_AGREEMENT
        direction = IntelligenceDirection.BEARISH
        strength = bear_total
        confidence = (CONFIDENCE_AGREEMENT_MULTI if len(bear_votes) >= 2
                      else CONFIDENCE_AGREEMENT_SINGLE)
    return _finish_result(inp, status=IntelligenceStatus.SUCCESS,
                          direction=direction,
                          strength=float(strength), confidence=confidence,
                          observation=IntelligenceObservation(
                              metric_name=outcome.value,
                              value=float(strength), unit="score_0_1"),
                          evidence=evidence, issues=issues)
