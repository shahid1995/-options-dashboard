"""Day 30 — Strike-ranking contracts (approved design).

Typed, frozen, deterministic representations for the nine-factor
best-strike ranking boundary:

    StrikeCandidateInput (identity + nine explicit factor observations)
        + RankingWeights (nine finite weights summing to 1.0)
        -> rank_strikes(...)
        -> StrikeRankingResult (ranked + suppressed)

Semantics locked here
---------------------
* Every factor is an explicit normalized suitability score in [0,1]
  supplied by an upstream boundary -- the ranking engine never synthesizes
  a factor from a label, never recalculates liquidity/spread/IV/Greeks/
  positioning/GEX/distance/objective/risk, and never reinterprets market
  meaning (high/low IV, delta sign, GEX sign, OI concentration) into
  suitability.
* Missing factor == genuinely missing: absent from the candidate or in an
  INSUFFICIENT state -- NEVER coerced to 0.0 and never silently rewarded
  or punished.  A measured zero score is a present, usable value.
* rank_score, confidence and data quality are separate fields that never
  influence one another.
* The Day-28 Opportunity identity/provenance is preserved by reference
  (immutable); ranking never mutates it.
* Identity is caller-supplied and deterministic: no UUID/random/wall-clock.
* Invalid numeric input (NaN / inf / out-of-range) fails validation --
  never silently converted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance, QualityState
from app.market_data.quality import QualityResult
from app.opportunity.contracts import Opportunity

#: Day-30 contract version (independent of the Day-19/28 contracts).
STRIKE_RANKING_CONTRACT_VERSION = "1.0.0"

#: Numeric policy: weight sums must equal 1.0 within this tolerance.
_WEIGHT_SUM_TOLERANCE = 1e-9


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class OptionType(str, Enum):
    """Option side vocabulary (CE/PE) used by the Day-30 contract.

    Fixed member order (CE, PE) defines the ascending tie-break order.
    """

    CE = "CE"
    PE = "PE"


class RankingFactor(str, Enum):
    """The nine Master-Plan ranking factors (fixed declaration order)."""

    LIQUIDITY = "liquidity"
    SPREAD_QUALITY = "spread_quality"
    IV = "iv"
    GREEKS = "greeks"
    POSITIONING = "positioning"
    GEX = "gex"
    DISTANCE_TO_SPOT = "distance_to_spot"
    STRATEGY_OBJECTIVE = "strategy_objective"
    RISK = "risk"


class StrikeRankingStatus(str, Enum):
    """Result-level status."""

    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    NOTHING_ELIGIBLE = "NOTHING_ELIGIBLE"


class SuppressionReason(str, Enum):
    """Deterministic reason a candidate was not ranked."""

    MISSING_FACTOR = "MISSING_FACTOR"
    UNUSABLE_FACTOR = "UNUSABLE_FACTOR"


# ---------------------------------------------------------------------------
# Value helpers (deterministic)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")


def _require_range(value: float, name: str) -> None:
    _require_finite(value, name)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be within [0, 1]")


# ---------------------------------------------------------------------------
# Factor observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorObservation:
    """One explicit normalized factor suitability score.

    ``score`` is the upstream-normalized suitability in [0,1] (higher =
    more suitable under the caller's stated objective).  ``state`` reuses
    the Day-12 ``QualityState`` vocabulary: EXCELLENT/GOOD/DEGRADED are
    usable and visible; INSUFFICIENT makes the factor unusable (the
    candidate is suppressed -- never scored with a fabricated value).
    ``raw`` optionally carries the raw market value for explanation only;
    ranking operates solely on ``score``.
    ``provenance`` is the canonical Day-9 ``Provenance`` of the individual
    factor observation (reused, not a second provenance model): it
    identifies where this factor's normalized score originated and is
    propagated through ranking into every ``FactorContribution`` so an
    auditor can trace each contribution back to its source.  ``None``
    means genuinely missing -- never fabricated.
    """

    factor: RankingFactor
    score: float
    state: QualityState = QualityState.EXCELLENT
    raw: float | str | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.factor, RankingFactor):
            raise ValueError("factor must be a RankingFactor")
        _require_range(self.score, "score")
        if not isinstance(self.state, QualityState):
            raise ValueError("state must be a Day-12 QualityState")
        if self.raw is not None and isinstance(self.raw, float):
            _require_finite(self.raw, "raw")
        if self.provenance is not None and \
                not isinstance(self.provenance, Provenance):
            raise ValueError(
                "provenance must be a canonical Provenance or None")

    @property
    def usable(self) -> bool:
        return self.state is not QualityState.INSUFFICIENT

    def to_dict(self) -> dict:
        return {
            "factor": self.factor.value,
            "score": self.score,
            "state": self.state.value,
            "raw": self.raw,
            "provenance": _fmt_provenance(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactorObservation":
        return cls(
            factor=RankingFactor(data["factor"]),
            score=data["score"],
            state=QualityState(data["state"]),
            raw=data.get("raw"),
            provenance=_provenance_from_dict(data.get("provenance")),
        )


# ---------------------------------------------------------------------------
# Candidate / weights / input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrikeCandidateInput:
    """One strike candidate: stable identity + explicit factor set.

    ``opportunity`` is the originating Day-28 Opportunity (immutable
    reference, optional); ``confidence`` and ``quality`` are independent
    caller-supplied context echoed through ranking -- they never change
    the ranking score.  ``factors`` may carry any subset: a candidate is
    fully ranked only when all nine factors are present and usable.
    """

    candidate_id: str
    underlying: str
    option_type: OptionType
    strike: float
    factors: tuple[FactorObservation, ...]
    expiry: str | None = None
    opportunity: Opportunity | None = None
    confidence: float | None = None
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "candidate_id")
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not isinstance(self.option_type, OptionType):
            raise ValueError("option_type must be an OptionType (CE/PE)")
        _require_finite(self.strike, "strike")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if not isinstance(self.factors, tuple) or not self.factors \
                or not all(isinstance(f, FactorObservation) for f in self.factors):
            raise ValueError("factors must be a non-empty tuple of FactorObservation")
        seen: set[RankingFactor] = set()
        for f in self.factors:
            if f.factor in seen:
                raise ValueError(f"duplicate factor observation {f.factor.value}")
            seen.add(f.factor)
        if self.opportunity is not None and \
                not isinstance(self.opportunity, Opportunity):
            raise ValueError("opportunity must be a Day-28 Opportunity or None")
        if self.confidence is not None:
            _require_range(self.confidence, "confidence")
        if self.quality is not None and \
                not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")

    # -- Opportunity projections (never fabricated when absent) -------------
    @property
    def opportunity_id(self) -> str | None:
        return self.opportunity.opportunity_id if self.opportunity else None

    @property
    def provenance(self) -> Provenance | None:
        return self.opportunity.provenance if self.opportunity else None

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "underlying": self.underlying,
            "option_type": self.option_type.value,
            "strike": self.strike,
            "expiry": self.expiry,
            "factors": [f.to_dict() for f in self.factors],
            "opportunity": self.opportunity.to_dict() if self.opportunity else None,
            "confidence": self.confidence,
            "quality": _quality_projection(self.quality),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrikeCandidateInput":
        return cls(
            candidate_id=data["candidate_id"],
            underlying=data["underlying"],
            option_type=OptionType(data["option_type"]),
            strike=data["strike"],
            expiry=data.get("expiry"),
            factors=tuple(FactorObservation.from_dict(f)
                          for f in data["factors"]),
            opportunity=Opportunity.from_dict(data["opportunity"])
            if data.get("opportunity") else None,
            confidence=data.get("confidence"),
            quality=_quality_from_projection(data.get("quality")),
        )


@dataclass(frozen=True)
class RankingWeights:
    """Nine explicit non-negative weights summing exactly to 1.0.

    Defaults are the approved design weights
    (liquidity 0.15, spread quality 0.15, and 0.10 for the other seven).
    Weights are configuration captured in the request and echoed in the
    result; they are not claimed to be statistically optimal.
    """

    liquidity: float = 0.15
    spread_quality: float = 0.15
    iv: float = 0.10
    greeks: float = 0.10
    positioning: float = 0.10
    gex: float = 0.10
    distance_to_spot: float = 0.10
    strategy_objective: float = 0.10
    risk: float = 0.10

    def __post_init__(self) -> None:
        for name in self._field_names():
            _require_finite(float(getattr(self, name)), name)
            if getattr(self, name) < 0.0:
                raise ValueError(f"weight {name} must be non-negative")
        if not math.isclose(self.as_sum(), 1.0, abs_tol=_WEIGHT_SUM_TOLERANCE):
            raise ValueError(
                "weights must sum to exactly 1.0 "
                f"(sum={self.as_sum():.12f})")

    def _field_names(self) -> tuple[str, ...]:
        return ("liquidity", "spread_quality", "iv", "greeks", "positioning",
                "gex", "distance_to_spot", "strategy_objective", "risk")

    def as_sum(self) -> float:
        return sum(float(getattr(self, name)) for name in self._field_names())

    def weight(self, factor: RankingFactor) -> float:
        return float(getattr(self, factor.value))

    def to_dict(self) -> dict:
        return {name: float(getattr(self, name)) for name in self._field_names()}

    @classmethod
    def from_dict(cls, data: dict) -> "RankingWeights":
        return cls(**{name: data[name] for name in
                      ("liquidity", "spread_quality", "iv", "greeks",
                       "positioning", "gex", "distance_to_spot",
                       "strategy_objective", "risk")})


@dataclass(frozen=True)
class StrikeRankingInput:
    """Deterministic strike-ranking request.

    ``objective_id`` names the explicit strategy objective under which the
    factor suitability scores were produced (explanation metadata only --
    Day 30 never infers an objective and never builds a strategy template).
    """

    candidates: tuple[StrikeCandidateInput, ...]
    weights: RankingWeights
    objective_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not all(
                isinstance(c, StrikeCandidateInput) for c in self.candidates):
            raise ValueError("candidates must be a tuple of StrikeCandidateInput")
        if not isinstance(self.weights, RankingWeights):
            raise ValueError("weights must be a RankingWeights")
        if self.objective_id is not None:
            _require_text(self.objective_id, "objective_id")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorContribution:
    """Structured contribution of one factor to the total ranking score.

    ``provenance`` is the preserved factor-level provenance of the source
    ``FactorObservation`` -- it survives ranking so every contribution can
    be audited back to its originating factor source.
    """

    factor: RankingFactor
    score: float
    weight: float
    contribution: float
    state: QualityState
    raw: float | str | None = None
    provenance: Provenance | None = None

    def to_dict(self) -> dict:
        return {
            "factor": self.factor.value,
            "score": self.score,
            "weight": self.weight,
            "contribution": self.contribution,
            "state": self.state.value,
            "raw": self.raw,
            "provenance": _fmt_provenance(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactorContribution":
        return cls(
            factor=RankingFactor(data["factor"]),
            score=data["score"],
            weight=data["weight"],
            contribution=data["contribution"],
            state=QualityState(data["state"]),
            raw=data.get("raw"),
            provenance=_provenance_from_dict(data.get("provenance")),
        )


@dataclass(frozen=True)
class RankedStrike:
    """One fully ranked strike with its explanation."""

    candidate_id: str
    underlying: str
    option_type: OptionType
    strike: float
    rank: int
    rank_score: float
    contributions: tuple[FactorContribution, ...]
    explanation: str
    expiry: str | None = None
    opportunity: Opportunity | None = None
    confidence: float | None = None
    quality: QualityResult | None = None

    @property
    def opportunity_id(self) -> str | None:
        return self.opportunity.opportunity_id if self.opportunity else None

    @property
    def provenance(self) -> Provenance | None:
        return self.opportunity.provenance if self.opportunity else None

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "underlying": self.underlying,
            "option_type": self.option_type.value,
            "strike": self.strike,
            "expiry": self.expiry,
            "rank": self.rank,
            "rank_score": self.rank_score,
            "contributions": [c.to_dict() for c in self.contributions],
            "explanation": self.explanation,
            "opportunity": self.opportunity.to_dict() if self.opportunity else None,
            "confidence": self.confidence,
            "quality": _quality_projection(self.quality),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RankedStrike":
        return cls(
            candidate_id=data["candidate_id"],
            underlying=data["underlying"],
            option_type=OptionType(data["option_type"]),
            strike=data["strike"],
            expiry=data.get("expiry"),
            rank=data["rank"],
            rank_score=data["rank_score"],
            contributions=tuple(FactorContribution.from_dict(c)
                                for c in data["contributions"]),
            explanation=data["explanation"],
            opportunity=Opportunity.from_dict(data["opportunity"])
            if data.get("opportunity") else None,
            confidence=data.get("confidence"),
            quality=_quality_from_projection(data.get("quality")),
        )


@dataclass(frozen=True)
class SuppressedStrike:
    """A candidate excluded from ranking (deterministic reason + factors)."""

    candidate_id: str
    underlying: str
    option_type: OptionType
    strike: float
    reason: SuppressionReason
    factors: tuple[RankingFactor, ...]
    detail: str
    expiry: str | None = None

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "underlying": self.underlying,
            "option_type": self.option_type.value,
            "strike": self.strike,
            "expiry": self.expiry,
            "reason": self.reason.value,
            "factors": [f.value for f in self.factors],
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SuppressedStrike":
        return cls(
            candidate_id=data["candidate_id"],
            underlying=data["underlying"],
            option_type=OptionType(data["option_type"]),
            strike=data["strike"],
            expiry=data.get("expiry"),
            reason=SuppressionReason(data["reason"]),
            factors=tuple(RankingFactor(f) for f in data["factors"]),
            detail=data["detail"],
        )


@dataclass(frozen=True)
class StrikeRankingResult:
    """Deterministic ranking result (ranked sorted, suppressed listed)."""

    status: StrikeRankingStatus
    ranked: tuple[RankedStrike, ...]
    suppressed: tuple[SuppressedStrike, ...]
    weights: RankingWeights
    objective_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "contract": "strike_ranking.result",
            "version": STRIKE_RANKING_CONTRACT_VERSION,
            "status": self.status.value,
            "ranked": [r.to_dict() for r in self.ranked],
            "suppressed": [s.to_dict() for s in self.suppressed],
            "weights": self.weights.to_dict(),
            "objective_id": self.objective_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrikeRankingResult":
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        return cls(
            status=StrikeRankingStatus(data["status"]),
            ranked=tuple(RankedStrike.from_dict(r) for r in data["ranked"]),
            suppressed=tuple(SuppressedStrike.from_dict(s)
                             for s in data["suppressed"]),
            weights=RankingWeights.from_dict(data["weights"]),
            objective_id=data.get("objective_id"),
        )


# ---------------------------------------------------------------------------
# Provenance projection helpers (JSON-safe; canonical Day-9 shape)
# ---------------------------------------------------------------------------


def _fmt_provenance(prov: Provenance | None) -> dict | None:
    """Canonical JSON-safe Provenance shape (same fields/shape used by the
    intelligence contracts): datetimes serialize as ISO-8601 strings."""
    if prov is None:
        return None
    return {
        "source": prov.source,
        "collection_mode": prov.collection_mode,
        "received_at": prov.received_at.isoformat(),
        "normalization_version": prov.normalization_version,
        "contract_version": prov.contract_version,
        "transformation_id": prov.transformation_id,
    }


def _provenance_from_dict(data: dict | None) -> Provenance | None:
    if not data:
        return None
    return Provenance(
        source=data["source"],
        collection_mode=data["collection_mode"],
        received_at=datetime.fromisoformat(data["received_at"]),
        normalization_version=data["normalization_version"],
        contract_version=data["contract_version"],
        transformation_id=data.get("transformation_id"),
    )


# ---------------------------------------------------------------------------
# Quality projection helpers (JSON-safe; round-trip preserves state+score)
# ---------------------------------------------------------------------------


def _quality_projection(quality: QualityResult | None) -> dict | None:
    if quality is None:
        return None
    return {
        "quality_state": quality.quality_state.value,
        "quality_score": quality.quality_score,
    }


def _quality_from_projection(data: dict | None) -> QualityResult | None:
    if not data:
        return None
    return QualityResult(
        quality_score=int(data["quality_score"]),
        quality_state=QualityState(data["quality_state"]),
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=None,
        observation_time=None,
        observation_type="STRIKE_RANKING",
        contract_version="1.0.0",
        reference_time=None,
    )
