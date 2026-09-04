"""Day 29 — Scalping Opportunity Engine.

Deterministic scalping-candidate discovery on the Day-28 pipeline
(Observation -> Signal -> Setup -> Opportunity) with strict, explicit
freshness semantics:

    typed evidence (intelligence results)
        -> freshness evaluation   (caller-supplied ``as_of``; never the
                                   wall clock; timestamps never invented)
        -> eligibility cascade    (deterministic first-match suppression)
        -> Day-28 opportunity chain
        -> deterministic ranking  (documented additive formula)
    STOP at Opportunity -- never an order, never an execution intent.

Freshness semantics reuse the Day-12 documented freshness window
(``market_data/quality.py`` ``MarketDataQualityConfig``: fresh <= 60s,
stale > 300s by default) as *eligibility gates*, not quality scoring:
the engine never recomputes Day-12 quality.

Rules
-----
* ``as_of`` is the caller's explicit deterministic reference; ``None``
  means freshness cannot be established and every candidate is suppressed
  (``NO_REFERENCE_TIME``) -- missing freshness is never guessed.
* Reference timestamps are never invented; missing timestamps are never
  fresh; future timestamps are invalid, never fresh.
* FRESH (age <= fresh) accepted; DECAYING (fresh < age <= stale) degrades
  the freshness rank component but does not drop the candidate; STALE
  (age > stale) suppresses.  The interpretation itself may be FRESH or
  DECAYING but never STALE; any STALE / NO_TIMESTAMP / INVALID_TIMESTAMP
  context evidence suppresses the candidate.
* Interpretation gates mirror Days 20-26/28: SUCCESS status,
  BULLISH/BEARISH direction, present-and-usable quality (state !=
  INSUFFICIENT; DEGRADED usable and visible).  Missing != zero; missing
  context roles are not evidence and never oppose.
* Only a SUCCESS directional context read can corroborate (same
  direction) or conflict (opposite direction) with the interpretation.
  NEUTRAL / MIXED / UNKNOWN / non-SUCCESS context never opposes.
* ``role`` labels are caller-supplied explanation metadata only --
  direction is never derived from a role label.
* Ranking is ``clamp(0.30*freshness + 0.25*quality_score/100 +
  0.25*signal_strength + 0.20*confidence, 0, 1)`` with the weights
  explicit module constants below.  signal_strength, confidence and the
  Day-12 quality envelope remain separate and are preserved verbatim on
  the Day-28 Opportunity.
* Identity is deterministic (derived from the caller-supplied candidate
  id); no UUID / random / wall-clock values anywhere.

The module is pure: no wall clock, no randomness, no network, no
database, no filesystem, no broker and no execution behavior (AST-guarded
in tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import QualityState
from app.intelligence.contracts import (
    IntelligenceDirection,
    IntelligenceResult,
    IntelligenceStatus,
)
from app.opportunity.contracts import Observation, Opportunity
from app.opportunity.pipeline import discover_opportunity

#: Day-29 contract version (independent of the Day-19/28 contracts).
SCALPING_CONTRACT_VERSION = "1.0.0"

#: Documented ranking weights (deterministic, sum to 1.0).
RANK_W_FRESHNESS = 0.30
RANK_W_QUALITY = 0.25
RANK_W_STRENGTH = 0.25
RANK_W_CONFIDENCE = 0.20

#: Freshness per-item score used inside the freshness rank component.
_SCORE_FRESH = 1.0
_SCORE_DECAYING = 0.75


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class EvidenceRole(str, Enum):
    """Caller-supplied explanation metadata for a context evidence item.

    A role label never drives direction -- only the carried
    ``IntelligenceResult`` semantics do.  Missing roles are simply absent.
    """

    PRICE = "PRICE"
    POSITIONING = "POSITIONING"
    FLOW = "FLOW"
    GEX_GAMMA = "GEX_GAMMA"
    REGIME = "REGIME"
    EVENT_EXPIRY = "EVENT_EXPIRY"


class FreshnessState(str, Enum):
    """Deterministic freshness state of one evidence item at ``as_of``."""

    FRESH = "FRESH"
    DECAYING = "DECAYING"
    STALE = "STALE"
    NO_TIMESTAMP = "NO_TIMESTAMP"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"


class SuppressionReason(str, Enum):
    """Deterministic reason a candidate was not ranked (first match)."""

    NO_REFERENCE_TIME = "NO_REFERENCE_TIME"
    UNINTERPRETABLE = "UNINTERPRETABLE"
    INSUFFICIENT_QUALITY = "INSUFFICIENT_QUALITY"
    NON_DIRECTIONAL = "NON_DIRECTIONAL"
    NO_TIMESTAMP = "NO_TIMESTAMP"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    CONFLICTED_CONTEXT = "CONFLICTED_CONTEXT"


class ScalpingStatus(str, Enum):
    """Result-level status."""

    SUCCESS = "SUCCESS"
    NOTHING_ELIGIBLE = "NOTHING_ELIGIBLE"
    EMPTY = "EMPTY"


# ---------------------------------------------------------------------------
# Value helpers (deterministic — never wall-clock / random / IO)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _is_aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _age_seconds(ts: datetime, as_of: datetime) -> float:
    return (as_of - ts).total_seconds()


def _fmt_age(age: float | None) -> str:
    return "None" if age is None else f"{age:.3f}"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalpingFreshnessPolicy:
    """Explicit freshness thresholds (same semantic as Day-12 defaults).

    FRESH when ``age <= fresh_seconds``; DECAYING when
    ``fresh_seconds < age <= stale_seconds``; STALE when
    ``age > stale_seconds``.  Boundary ``age == fresh_seconds`` is FRESH
    and ``age == stale_seconds`` is DECAYING (STALE is strict).
    """

    fresh_seconds: float = 60.0
    stale_seconds: float = 300.0

    def __post_init__(self) -> None:
        for name, value in (("fresh_seconds", self.fresh_seconds),
                            ("stale_seconds", self.stale_seconds)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a finite number")
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"{name} must be finite")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if not self.stale_seconds > self.fresh_seconds:
            raise ValueError("stale_seconds must exceed fresh_seconds")


@dataclass(frozen=True)
class ContextEvidence:
    """One supporting channel read (any intelligence engine output).

    ``role`` is explanation metadata only.  Only a SUCCESS directional
    read can corroborate or conflict with the interpretation.
    """

    role: EvidenceRole
    result: IntelligenceResult

    def __post_init__(self) -> None:
        if not isinstance(self.role, EvidenceRole):
            raise ValueError("role must be an EvidenceRole")
        if not isinstance(self.result, IntelligenceResult):
            raise ValueError("result must be a Day-19 IntelligenceResult")


@dataclass(frozen=True)
class ScalpingCandidateInput:
    """Pure-data scalping candidate: one directional interpretation plus
    optional supporting channel context."""

    candidate_id: str
    underlying: str
    interpretation: IntelligenceResult
    context: tuple[ContextEvidence, ...] = ()
    expiry: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not isinstance(self.interpretation, IntelligenceResult):
            raise ValueError("interpretation must be a Day-19 IntelligenceResult")
        if not isinstance(self.context, tuple) or not all(
                isinstance(c, ContextEvidence) for c in self.context):
            raise ValueError("context must be a tuple of ContextEvidence")


@dataclass(frozen=True)
class ScalpingInput:
    """Deterministic scalping evaluation request.

    ``as_of`` is the caller-supplied freshness reference (must be
    genuinely timezone-aware when present); the engine never reads the
    current time.
    """

    candidates: tuple[ScalpingCandidateInput, ...]
    as_of: datetime | None = None
    policy: ScalpingFreshnessPolicy = ScalpingFreshnessPolicy()

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not all(
                isinstance(c, ScalpingCandidateInput) for c in self.candidates):
            raise ValueError("candidates must be a tuple of ScalpingCandidateInput")
        if not isinstance(self.policy, ScalpingFreshnessPolicy):
            raise ValueError("policy must be a ScalpingFreshnessPolicy")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceFreshness:
    """Freshness row for one supplied evidence item (deterministic)."""

    label: str
    calculation_id: str
    state: FreshnessState
    age_seconds: float | None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "calculation_id": self.calculation_id,
            "state": self.state.value,
            "age_seconds": self.age_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceFreshness":
        return cls(
            label=data["label"],
            calculation_id=data["calculation_id"],
            state=FreshnessState(data["state"]),
            age_seconds=data["age_seconds"],
        )


@dataclass(frozen=True)
class RankedScalpingOpportunity:
    """One eligible candidate ranked under the documented formula.

    ``opportunity`` is the *unchanged* Day-28 ``Opportunity`` (the
    interpretation object is preserved by identity through the chain).
    """

    candidate_id: str
    opportunity: Opportunity
    rank: float
    explanation: str
    evidence_freshness: tuple[EvidenceFreshness, ...]

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "opportunity": self.opportunity.to_dict(),
            "rank": self.rank,
            "explanation": self.explanation,
            "evidence_freshness": [e.to_dict() for e in self.evidence_freshness],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RankedScalpingOpportunity":
        return cls(
            candidate_id=data["candidate_id"],
            opportunity=Opportunity.from_dict(data["opportunity"]),
            rank=data["rank"],
            explanation=data["explanation"],
            evidence_freshness=tuple(
                EvidenceFreshness.from_dict(e) for e in data["evidence_freshness"]
            ),
        )


@dataclass(frozen=True)
class SuppressedCandidate:
    """A candidate that failed the eligibility cascade (deterministic)."""

    candidate_id: str
    underlying: str
    reason: SuppressionReason
    detail: str

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "underlying": self.underlying,
            "reason": self.reason.value,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SuppressedCandidate":
        return cls(
            candidate_id=data["candidate_id"],
            underlying=data["underlying"],
            reason=SuppressionReason(data["reason"]),
            detail=data["detail"],
        )


@dataclass(frozen=True)
class ScalpingResult:
    """Deterministic scalping evaluation result.

    ``ranked`` is sorted (rank desc, then underlying/candidate_id asc);
    stale / insufficient / conflicted candidates appear only in
    ``suppressed`` with their reasons.
    """

    status: ScalpingStatus
    ranked: tuple[RankedScalpingOpportunity, ...]
    suppressed: tuple[SuppressedCandidate, ...]
    as_of: datetime | None
    policy: ScalpingFreshnessPolicy

    def to_dict(self) -> dict:
        return {
            "contract": "opportunity.scalping_result",
            "version": SCALPING_CONTRACT_VERSION,
            "status": self.status.value,
            "as_of": self.as_of.isoformat() if self.as_of is not None else None,
            "policy": {
                "fresh_seconds": self.policy.fresh_seconds,
                "stale_seconds": self.policy.stale_seconds,
            },
            "ranked": [r.to_dict() for r in self.ranked],
            "suppressed": [s.to_dict() for s in self.suppressed],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScalpingResult":
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        policy = ScalpingFreshnessPolicy(
            fresh_seconds=data["policy"]["fresh_seconds"],
            stale_seconds=data["policy"]["stale_seconds"],
        )
        as_of_raw = data.get("as_of")
        return cls(
            status=ScalpingStatus(data["status"]),
            ranked=tuple(
                RankedScalpingOpportunity.from_dict(r) for r in data["ranked"]
            ),
            suppressed=tuple(
                SuppressedCandidate.from_dict(s) for s in data["suppressed"]
            ),
            as_of=datetime.fromisoformat(as_of_raw) if as_of_raw else None,
            policy=policy,
        )


# ---------------------------------------------------------------------------
# Freshness evaluation (pure)
# ---------------------------------------------------------------------------


def _freshness_state(age_seconds: float | None,
                     policy: ScalpingFreshnessPolicy) -> FreshnessState:
    """Deterministic freshness classification of one age value."""
    if age_seconds is None:
        return FreshnessState.NO_TIMESTAMP
    if age_seconds < 0:
        return FreshnessState.INVALID_TIMESTAMP
    if age_seconds <= policy.fresh_seconds:
        return FreshnessState.FRESH
    if age_seconds <= policy.stale_seconds:
        return FreshnessState.DECAYING
    return FreshnessState.STALE


def _item_state(result: IntelligenceResult, as_of: datetime,
                policy: ScalpingFreshnessPolicy) -> tuple[FreshnessState, float | None]:
    if result.reference_timestamp is None:
        return FreshnessState.NO_TIMESTAMP, None
    age = _age_seconds(result.reference_timestamp, as_of)
    return _freshness_state(age, policy), age


def _directional(value: IntelligenceDirection | None) -> bool:
    return value in (IntelligenceDirection.BULLISH, IntelligenceDirection.BEARISH)


# ---------------------------------------------------------------------------
# Eligibility cascade
# ---------------------------------------------------------------------------


def _suppress(candidate: ScalpingCandidateInput, reason: SuppressionReason,
              detail: str) -> SuppressedCandidate:
    return SuppressedCandidate(
        candidate_id=candidate.candidate_id,
        underlying=candidate.underlying,
        reason=reason,
        detail=detail,
    )


def _context_detail(role: EvidenceRole, result: IntelligenceResult, *,
                    age: float | None, reason: SuppressionReason,
                    policy: ScalpingFreshnessPolicy) -> str:
    r = role.value
    if reason is SuppressionReason.NO_TIMESTAMP:
        return (f"context[{r}] ({result.calculation_id}) has no reference "
                "timestamp -- freshness is never guessed")
    if reason is SuppressionReason.INVALID_TIMESTAMP:
        return (f"context[{r}] ({result.calculation_id}) reference timestamp "
                f"is in the future by {_fmt_age(-age)}s -- never fresh")
    return (f"context[{r}] ({result.calculation_id}) age "
            f"{_fmt_age(age)}s exceeds stale {policy.stale_seconds:.1f}s")


# ---------------------------------------------------------------------------
# Ranking (documented formula)
# ---------------------------------------------------------------------------


def _rank_explanation(rank: float, fresh_component: float,
                      states: tuple[str, ...], quality_score: int,
                      strength: float, confidence: float) -> str:
    return (f"rank {rank:.4f} = 0.30*{fresh_component:.4f}(freshness "
            f"[{','.join(states)}]) + 0.25*{quality_score / 100.0:.4f}"
            f"(quality {quality_score}/100) + 0.25*{strength:.4f}(strength) "
            f"+ 0.20*{confidence:.4f}(confidence)")


def _rank_candidate(candidate: ScalpingCandidateInput,
                    as_of: datetime,
                    policy: ScalpingFreshnessPolicy) -> RankedScalpingOpportunity:
    """Rank one eligible candidate and run it through the Day-28 chain."""
    policy_row = candidate.interpretation
    items: list[tuple[str, IntelligenceResult, FreshnessState, float | None]] = [
        ("interpretation", policy_row,
         *_item_state(policy_row, as_of, policy))
    ]
    for ctx in candidate.context:
        items.append(
            (ctx.role.value, ctx.result,
             *_item_state(ctx.result, as_of, policy)))
    rows = tuple(
        EvidenceFreshness(label=label, calculation_id=result.calculation_id,
                          state=state, age_seconds=age)
        for label, result, state, age in items
    )
    scores = [_SCORE_FRESH if s is FreshnessState.FRESH else _SCORE_DECAYING
              for _, _, s, _ in items]
    fresh_component = sum(scores) / len(scores)
    quality = policy_row.quality
    assert quality is not None  # guaranteed by the eligibility cascade
    strength = policy_row.signal_strength
    confidence = policy_row.confidence
    assert strength is not None and confidence is not None  # SUCCESS contract
    rank = (RANK_W_FRESHNESS * fresh_component
            + RANK_W_QUALITY * (quality.quality_score / 100.0)
            + RANK_W_STRENGTH * strength
            + RANK_W_CONFIDENCE * confidence)
    rank = max(0.0, min(1.0, rank))
    explanation = _rank_explanation(
        rank, fresh_component,
        tuple(s.value for _, _, s, _ in items),
        quality.quality_score, strength, confidence)
    observation = Observation(
        observation_id=f"obs-{candidate.candidate_id}",
        underlying=candidate.underlying,
        expiry=candidate.expiry,
        upstream=policy_row,
    )
    opportunity = discover_opportunity(
        observation,
        signal_id=f"sig-{candidate.candidate_id}",
        setup_id=f"stp-{candidate.candidate_id}",
        opportunity_id=f"opp-{candidate.candidate_id}",
    )
    return RankedScalpingOpportunity(
        candidate_id=candidate.candidate_id,
        opportunity=opportunity,
        rank=rank,
        explanation=explanation,
        evidence_freshness=rows,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_scalping(inp: ScalpingInput) -> ScalpingResult:
    """Evaluate all candidates: suppress ineligible ones, rank the rest.

    Deterministic: identical inputs produce identical ranked and
    suppressed tuples (ordering: rank desc, underlying/candidate id asc).
    """
    if not isinstance(inp, ScalpingInput):
        raise ValueError("evaluate_scalping requires a ScalpingInput")
    if inp.as_of is not None and not _is_aware(inp.as_of):
        raise ValueError("as_of must be genuinely timezone-aware when present")
    if not inp.candidates:
        return ScalpingResult(
            status=ScalpingStatus.EMPTY,
            ranked=(),
            suppressed=(),
            as_of=inp.as_of,
            policy=inp.policy,
        )
    if inp.as_of is None:
        return ScalpingResult(
            status=ScalpingStatus.NOTHING_ELIGIBLE,
            ranked=(),
            suppressed=tuple(
                _suppress(c, SuppressionReason.NO_REFERENCE_TIME,
                          "as_of is None -- freshness cannot be established "
                          "and is never guessed")
                for c in inp.candidates),
            as_of=None,
            policy=inp.policy,
        )

    policy = inp.policy
    ranked: list[RankedScalpingOpportunity] = []
    suppressed: list[SuppressedCandidate] = []

    for candidate in inp.candidates:
        interp = candidate.interpretation

        if interp.status is not IntelligenceStatus.SUCCESS:
            suppressed.append(_suppress(
                candidate, SuppressionReason.UNINTERPRETABLE,
                f"interpretation status {interp.status.value} is not SUCCESS"))
            continue

        quality = interp.quality
        if quality is None or quality.quality_state is QualityState.INSUFFICIENT:
            suppressed.append(_suppress(
                candidate, SuppressionReason.INSUFFICIENT_QUALITY,
                "interpretation quality is missing or INSUFFICIENT "
                "(below the usable floor)"))
            continue

        if interp.direction is None or not _directional(interp.direction):
            suppressed.append(_suppress(
                candidate, SuppressionReason.NON_DIRECTIONAL,
                f"interpretation direction "
                f"{interp.direction.value if interp.direction else None} is "
                "not BULLISH/BEARISH -- a scalp needs a directional read"))
            continue

        if interp.reference_timestamp is None:
            suppressed.append(_suppress(
                candidate, SuppressionReason.NO_TIMESTAMP,
                "interpretation has no reference timestamp -- freshness is "
                "never guessed"))
            continue

        interp_age = _age_seconds(interp.reference_timestamp, inp.as_of)
        if interp_age < 0:
            suppressed.append(_suppress(
                candidate, SuppressionReason.INVALID_TIMESTAMP,
                f"interpretation reference timestamp is in the future by "
                f"{_fmt_age(-interp_age)}s -- never fresh"))
            continue

        # Context freshness gates (NO_TIMESTAMP / INVALID / STALE).
        context_blocked = False
        for ctx in candidate.context:
            state, age = _item_state(ctx.result, inp.as_of, policy)
            if state is FreshnessState.NO_TIMESTAMP:
                suppressed.append(_suppress(
                    candidate, SuppressionReason.NO_TIMESTAMP,
                    _context_detail(ctx.role, ctx.result, age=age,
                                    reason=SuppressionReason.NO_TIMESTAMP,
                                    policy=policy)))
                context_blocked = True
                break
            if state is FreshnessState.INVALID_TIMESTAMP:
                suppressed.append(_suppress(
                    candidate, SuppressionReason.INVALID_TIMESTAMP,
                    _context_detail(ctx.role, ctx.result, age=age,
                                    reason=SuppressionReason.INVALID_TIMESTAMP,
                                    policy=policy)))
                context_blocked = True
                break
            if state is FreshnessState.STALE:
                suppressed.append(_suppress(
                    candidate, SuppressionReason.STALE_EVIDENCE,
                    _context_detail(ctx.role, ctx.result, age=age,
                                    reason=SuppressionReason.STALE_EVIDENCE,
                                    policy=policy)))
                context_blocked = True
                break
        if context_blocked:
            continue

        interp_state = _freshness_state(interp_age, policy)
        if interp_state is FreshnessState.STALE:
            suppressed.append(_suppress(
                candidate, SuppressionReason.STALE_EVIDENCE,
                f"interpretation age {_fmt_age(interp_age)}s exceeds stale "
                f"{policy.stale_seconds:.1f}s"))
            continue

        # Directional conflict: only a SUCCESS directional context read can
        # oppose the interpretation direction.
        direction = interp.direction
        conflicted = None
        for ctx in candidate.context:
            ctx_result = ctx.result
            if ctx_result.status is IntelligenceStatus.SUCCESS \
                    and ctx_result.direction is not None \
                    and _directional(ctx_result.direction) \
                    and ctx_result.direction is not direction:
                conflicted = ctx
                break
        if conflicted is not None:
            ctx_result = conflicted.result
            suppressed.append(_suppress(
                candidate, SuppressionReason.CONFLICTED_CONTEXT,
                f"context[{conflicted.role.value}] ({ctx_result.calculation_id}) "
                f"direction {ctx_result.direction.value} opposes interpretation "
                f"{direction.value}"))
            continue

        ranked.append(_rank_candidate(candidate, inp.as_of, policy))

    ranked.sort(key=lambda r: (-r.rank, r.opportunity.underlying,
                                r.candidate_id))
    status = (ScalpingStatus.SUCCESS if ranked
              else ScalpingStatus.NOTHING_ELIGIBLE)
    return ScalpingResult(
        status=status,
        ranked=tuple(ranked),
        suppressed=tuple(suppressed),
        as_of=inp.as_of,
        policy=policy,
    )
