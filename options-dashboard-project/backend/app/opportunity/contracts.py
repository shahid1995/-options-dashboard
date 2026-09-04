"""Day 28 — Opportunity domain contracts.

Typed, frozen, deterministic domain representations for the pipeline

    Observation -> Signal -> Setup -> Opportunity

The upstream Day-19 ``IntelligenceResult`` (an approved Days 20-26 output)
is the single source of truth at every stage: the domain objects expose the
upstream projections (status / direction / signal strength / confidence /
quality / regime / horizon / provenance / timestamps / evidence) through
read-only properties, so no duplicated field can drift and no second
market-data system exists.

Structural and semantic invariants are enforced at construction:

* Observations may envelope any upstream ``IntelligenceResult`` (recording
  an incomplete upstream is legitimate; the pipeline gates block it later).
* Setups and Opportunities require a directional SUCCESS upstream read with
  present-and-usable quality (state != INSUFFICIENT; DEGRADED is usable and
  visible) and a present horizon -- the domain NEVER invents a horizon.
* Non-directional Signals (NEUTRAL / UNKNOWN / MIXED) are valid Signals but
  can never form a Setup.
* The authoritative Day-23 ``MarketRegime`` is preserved verbatim; regime
  labels alone never become direction.
* Identity is caller-supplied and deterministic (no UUID/random/wall-clock).
* ``to_dict``/``from_dict`` are deterministic and JSON-safe and round-trip
  the full upstream payload without losing evidence/quality/regime/
  provenance/timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    IntelligenceDirection,
    IntelligenceEvidence,
    IntelligenceResult,
    IntelligenceStatus,
    MarketRegime,
    TimeHorizon,
)

#: Domain contract version (independent of the Day-19 contract version).
OPPORTUNITY_CONTRACT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Vocabulary (explicit, broker-neutral)
# ---------------------------------------------------------------------------


class ObservationKind(str, Enum):
    """Kind of upstream observation this envelope carries.

    Only ``INTELLIGENCE_RESULT`` is produced today (Days 20-26 outputs are
    the approved upstream observations).  Additional kinds are reserved for
    upstreams that do not exist in the monolith yet -- never fabricated.
    """

    INTELLIGENCE_RESULT = "INTELLIGENCE_RESULT"


class ExpectedBehavior(str, Enum):
    """Explainable expected-behavior vocabulary (candidate language only).

    The Day-28 pipeline deterministically produces
    ``DIRECTIONAL_CONTINUATION_CANDIDATE`` from a directional read.  The
    remaining values are reserved vocabulary for upstream evidence the
    current Day-28 inputs do not carry -- never selected without evidence,
    never implied by a label.
    """

    DIRECTIONAL_CONTINUATION_CANDIDATE = "DIRECTIONAL_CONTINUATION_CANDIDATE"
    MEAN_REVERSION_CANDIDATE = "MEAN_REVERSION_CANDIDATE"
    BREAKOUT_CANDIDATE = "BREAKOUT_CANDIDATE"
    BREAKDOWN_CANDIDATE = "BREAKDOWN_CANDIDATE"
    VOLATILITY_EXPANSION_CANDIDATE = "VOLATILITY_EXPANSION_CANDIDATE"
    VOLATILITY_CONTRACTION_CANDIDATE = "VOLATILITY_CONTRACTION_CANDIDATE"


class OpportunityStatus(str, Enum):
    """Lifecycle status of an Opportunity (foundation vocabulary).

    ``CANDIDATE`` is the only status Day 28 produces: an opportunity is a
    discovered candidate awaiting later Strategy Candidate / Risk / User
    Decision stages.  Reserved members for later days are added additively
    by the strategy phase -- never produced here.
    """

    CANDIDATE = "CANDIDATE"


# ---------------------------------------------------------------------------
# Value helpers (deterministic — never wall-clock / random / IO)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware_or_none(ts: datetime | None, name: str) -> None:
    if ts is not None:
        if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
            raise ValueError(f"{name} must be genuinely timezone-aware when present")


def _usable_quality(quality: QualityResult | None) -> bool:
    """Documented usable floor (mirrors the established Days 20-26 rule):
    quality present and state != INSUFFICIENT.  DEGRADED remains usable and
    stays visible on the object."""
    if quality is None:
        return False
    return quality.quality_state is not QualityState.INSUFFICIENT


def _directional(value: IntelligenceDirection | None) -> bool:
    return value in (IntelligenceDirection.BULLISH, IntelligenceDirection.BEARISH)


def _validate_upstream_directional_usable(upstream: IntelligenceResult) -> None:
    """Semantic gates shared by Setup and Opportunity construction."""
    if upstream.status is not IntelligenceStatus.SUCCESS:
        raise ValueError(
            "a Setup/Opportunity requires a SUCCESS upstream read "
            f"(status={upstream.status.value})")
    if upstream.direction is None or not _directional(upstream.direction):
        raise ValueError(
            "a Setup/Opportunity requires a directional (BULLISH/BEARISH) "
            "upstream read")
    if upstream.time_horizon is None:
        raise ValueError(
            "a Setup/Opportunity requires an upstream time horizon -- the "
            "domain never invents one")
    if not _usable_quality(upstream.quality):
        raise ValueError(
            "a Setup/Opportunity requires present-and-usable quality "
            "(missing or INSUFFICIENT upstream quality cannot form one)")


# ---------------------------------------------------------------------------
# Stage 1 — Observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """Typed envelope over ONE authoritative upstream intelligence result.

    The upstream Day-19 ``IntelligenceResult`` is the single source of
    truth; every projection below reads it directly.  ``underlying`` /
    ``expiry`` are the instrument scope (the Day-19 envelope does not carry
    them; the caller supplies them exactly as every intelligence engine
    input does).
    """

    observation_id: str
    underlying: str
    upstream: IntelligenceResult
    expiry: str | None = None
    kind: ObservationKind = ObservationKind.INTELLIGENCE_RESULT

    def __post_init__(self) -> None:
        _require_text(self.observation_id, "observation_id")
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not isinstance(self.upstream, IntelligenceResult):
            raise ValueError("upstream must be a Day-19 IntelligenceResult")
        if not isinstance(self.kind, ObservationKind):
            raise ValueError("kind must be an ObservationKind")

    # -- upstream projections (read-only, zero drift) ------------------------
    @property
    def calculation_id(self) -> str:
        return self.upstream.calculation_id

    @property
    def status(self) -> IntelligenceStatus:
        return self.upstream.status

    @property
    def direction(self) -> IntelligenceDirection | None:
        return self.upstream.direction

    @property
    def signal_strength(self) -> float | None:
        return self.upstream.signal_strength

    @property
    def confidence(self) -> float | None:
        return self.upstream.confidence

    @property
    def time_horizon(self) -> TimeHorizon | None:
        return self.upstream.time_horizon

    @property
    def regime(self) -> MarketRegime | None:
        return self.upstream.regime

    @property
    def quality(self) -> QualityResult | None:
        return self.upstream.quality

    @property
    def provenance(self) -> Provenance | None:
        return self.upstream.provenance

    @property
    def reference_timestamp(self) -> datetime | None:
        return self.upstream.reference_timestamp

    @property
    def evidence(self) -> tuple[IntelligenceEvidence, ...]:
        return self.upstream.evidence

    # -- deterministic JSON-safe serialization ------------------------------
    def to_dict(self) -> dict:
        return {
            "contract": "opportunity.observation",
            "version": OPPORTUNITY_CONTRACT_VERSION,
            "observation_id": self.observation_id,
            "underlying": self.underlying,
            "expiry": self.expiry,
            "kind": self.kind.value,
            "upstream": self.upstream.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Observation":
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        return cls(
            observation_id=data["observation_id"],
            underlying=data["underlying"],
            expiry=data.get("expiry"),
            upstream=IntelligenceResult.from_dict(data["upstream"]),
            kind=ObservationKind(data["kind"]),
        )


# ---------------------------------------------------------------------------
# Stage 2 — Signal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """A meaningful interpretation of one observation.

    The pipeline creates Signals only from interpretable SUCCESS upstream
    observations (missing quality cannot become a Signal at all).
    Non-directional Signals (NEUTRAL / UNKNOWN / MIXED) are valid Signals
    but can never form a Setup.
    """

    signal_id: str
    observation_id: str
    underlying: str
    upstream: IntelligenceResult
    explanation: str
    expiry: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.signal_id, "signal_id")
        _require_text(self.observation_id, "observation_id")
        _require_text(self.underlying, "underlying")
        _require_text(self.explanation, "explanation")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not isinstance(self.upstream, IntelligenceResult):
            raise ValueError("upstream must be a Day-19 IntelligenceResult")

    # -- upstream projections (identical vocabulary to Observation) ----------
    @property
    def calculation_id(self) -> str:
        return self.upstream.calculation_id

    @property
    def status(self) -> IntelligenceStatus:
        return self.upstream.status

    @property
    def direction(self) -> IntelligenceDirection | None:
        return self.upstream.direction

    @property
    def signal_strength(self) -> float | None:
        return self.upstream.signal_strength

    @property
    def confidence(self) -> float | None:
        return self.upstream.confidence

    @property
    def time_horizon(self) -> TimeHorizon | None:
        return self.upstream.time_horizon

    @property
    def regime(self) -> MarketRegime | None:
        return self.upstream.regime

    @property
    def quality(self) -> QualityResult | None:
        return self.upstream.quality

    @property
    def provenance(self) -> Provenance | None:
        return self.upstream.provenance

    @property
    def reference_timestamp(self) -> datetime | None:
        return self.upstream.reference_timestamp

    @property
    def evidence(self) -> tuple[IntelligenceEvidence, ...]:
        return self.upstream.evidence

    # -- deterministic JSON-safe serialization ------------------------------
    def to_dict(self) -> dict:
        return {
            "contract": "opportunity.signal",
            "version": OPPORTUNITY_CONTRACT_VERSION,
            "signal_id": self.signal_id,
            "observation_id": self.observation_id,
            "underlying": self.underlying,
            "expiry": self.expiry,
            "explanation": self.explanation,
            "upstream": self.upstream.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Signal":
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        return cls(
            signal_id=data["signal_id"],
            observation_id=data["observation_id"],
            underlying=data["underlying"],
            expiry=data.get("expiry"),
            explanation=data["explanation"],
            upstream=IntelligenceResult.from_dict(data["upstream"]),
        )


# ---------------------------------------------------------------------------
# Stage 3 — Setup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Setup:
    """A structured directional trading-setup frame from one Signal.

    ``expected_behavior`` is deterministic candidate language;
    ``invalidation_conditions`` are non-empty, deterministic,
    state/evidence-based descriptions of the thesis boundary -- never
    stop-losses, cancellations, position management or broker actions.
    Construction enforces the shared directional-SUCCESS + usable-quality +
    present-horizon gates.
    """

    setup_id: str
    signal_id: str
    underlying: str
    upstream: IntelligenceResult
    expected_behavior: ExpectedBehavior
    invalidation_conditions: tuple[str, ...]
    expiry: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.setup_id, "setup_id")
        _require_text(self.signal_id, "signal_id")
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not isinstance(self.upstream, IntelligenceResult):
            raise ValueError("upstream must be a Day-19 IntelligenceResult")
        if not isinstance(self.expected_behavior, ExpectedBehavior):
            raise ValueError("expected_behavior must be an ExpectedBehavior")
        if not isinstance(self.invalidation_conditions, tuple) \
                or not self.invalidation_conditions:
            raise ValueError(
                "invalidation_conditions must be a non-empty tuple")
        if not all(isinstance(c, str) and c.strip()
                   for c in self.invalidation_conditions):
            raise ValueError(
                "every invalidation condition must be a non-blank string")
        _validate_upstream_directional_usable(self.upstream)

    # -- upstream projections (Setup requires a directional SUCCESS read) ----
    @property
    def calculation_id(self) -> str:
        return self.upstream.calculation_id

    @property
    def direction(self) -> IntelligenceDirection:
        assert self.upstream.direction is not None  # enforced above
        return self.upstream.direction

    @property
    def signal_strength(self) -> float | None:
        return self.upstream.signal_strength

    @property
    def confidence(self) -> float | None:
        return self.upstream.confidence

    @property
    def time_horizon(self) -> TimeHorizon:
        assert self.upstream.time_horizon is not None  # enforced above
        return self.upstream.time_horizon

    @property
    def regime(self) -> MarketRegime | None:
        return self.upstream.regime

    @property
    def quality(self) -> QualityResult:
        assert self.upstream.quality is not None  # enforced above
        return self.upstream.quality

    @property
    def provenance(self) -> Provenance | None:
        return self.upstream.provenance

    @property
    def reference_timestamp(self) -> datetime | None:
        return self.upstream.reference_timestamp

    @property
    def evidence(self) -> tuple[IntelligenceEvidence, ...]:
        return self.upstream.evidence

    # -- deterministic JSON-safe serialization ------------------------------
    def to_dict(self) -> dict:
        return {
            "contract": "opportunity.setup",
            "version": OPPORTUNITY_CONTRACT_VERSION,
            "setup_id": self.setup_id,
            "signal_id": self.signal_id,
            "underlying": self.underlying,
            "expiry": self.expiry,
            "expected_behavior": self.expected_behavior.value,
            "invalidation_conditions": list(self.invalidation_conditions),
            "upstream": self.upstream.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Setup":
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        return cls(
            setup_id=data["setup_id"],
            signal_id=data["signal_id"],
            underlying=data["underlying"],
            expiry=data.get("expiry"),
            expected_behavior=ExpectedBehavior(data["expected_behavior"]),
            invalidation_conditions=tuple(data["invalidation_conditions"]),
            upstream=IntelligenceResult.from_dict(data["upstream"]),
        )


# ---------------------------------------------------------------------------
# Stage 4 — Opportunity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Opportunity:
    """The final Day-28 discovery object.

    ``thesis`` is the deterministic, explainable answer to "why does this
    opportunity exist?"; every projection remains traceable to the upstream
    evidence through ``setup_id`` and the preserved ``upstream`` result.
    An Opportunity is a discovered CANDIDATE -- NOT an order, NOT an
    execution intent, NOT a risk decision.
    """

    opportunity_id: str
    setup_id: str
    underlying: str
    upstream: IntelligenceResult
    thesis: str
    expected_behavior: ExpectedBehavior
    invalidation_conditions: tuple[str, ...]
    expiry: str | None = None
    status: OpportunityStatus = OpportunityStatus.CANDIDATE

    def __post_init__(self) -> None:
        _require_text(self.opportunity_id, "opportunity_id")
        _require_text(self.setup_id, "setup_id")
        _require_text(self.underlying, "underlying")
        _require_text(self.thesis, "thesis")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        if not isinstance(self.upstream, IntelligenceResult):
            raise ValueError("upstream must be a Day-19 IntelligenceResult")
        if not isinstance(self.expected_behavior, ExpectedBehavior):
            raise ValueError("expected_behavior must be an ExpectedBehavior")
        if not isinstance(self.invalidation_conditions, tuple) \
                or not self.invalidation_conditions:
            raise ValueError(
                "invalidation_conditions must be a non-empty tuple")
        if not all(isinstance(c, str) and c.strip()
                   for c in self.invalidation_conditions):
            raise ValueError(
                "every invalidation condition must be a non-blank string")
        if not isinstance(self.status, OpportunityStatus):
            raise ValueError("status must be an OpportunityStatus")
        _validate_upstream_directional_usable(self.upstream)

    # -- upstream projections (same gates as Setup) --------------------------
    @property
    def calculation_id(self) -> str:
        return self.upstream.calculation_id

    @property
    def direction(self) -> IntelligenceDirection:
        assert self.upstream.direction is not None  # enforced above
        return self.upstream.direction

    @property
    def signal_strength(self) -> float | None:
        return self.upstream.signal_strength

    @property
    def confidence(self) -> float | None:
        return self.upstream.confidence

    @property
    def time_horizon(self) -> TimeHorizon:
        assert self.upstream.time_horizon is not None  # enforced above
        return self.upstream.time_horizon

    @property
    def regime(self) -> MarketRegime | None:
        return self.upstream.regime

    @property
    def quality(self) -> QualityResult:
        assert self.upstream.quality is not None  # enforced above
        return self.upstream.quality

    @property
    def provenance(self) -> Provenance | None:
        return self.upstream.provenance

    @property
    def reference_timestamp(self) -> datetime | None:
        return self.upstream.reference_timestamp

    @property
    def evidence(self) -> tuple[IntelligenceEvidence, ...]:
        return self.upstream.evidence

    # -- deterministic JSON-safe serialization ------------------------------
    def to_dict(self) -> dict:
        return {
            "contract": "opportunity.opportunity",
            "version": OPPORTUNITY_CONTRACT_VERSION,
            "opportunity_id": self.opportunity_id,
            "setup_id": self.setup_id,
            "underlying": self.underlying,
            "expiry": self.expiry,
            "thesis": self.thesis,
            "expected_behavior": self.expected_behavior.value,
            "invalidation_conditions": list(self.invalidation_conditions),
            "status": self.status.value,
            "upstream": self.upstream.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Opportunity":
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        return cls(
            opportunity_id=data["opportunity_id"],
            setup_id=data["setup_id"],
            underlying=data["underlying"],
            expiry=data.get("expiry"),
            thesis=data["thesis"],
            expected_behavior=ExpectedBehavior(data["expected_behavior"]),
            invalidation_conditions=tuple(data["invalidation_conditions"]),
            status=OpportunityStatus(data["status"]),
            upstream=IntelligenceResult.from_dict(data["upstream"]),
        )
