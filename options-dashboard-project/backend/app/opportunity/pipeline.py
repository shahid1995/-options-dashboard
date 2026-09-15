"""Day 28 — Opportunity pipeline transitions.

Deterministic stage transitions on the approved Days 19-26 foundation:

    to_signal(observation)        -- Observation -> Signal
    to_setup(signal)              -- Signal -> Setup
    to_opportunity(setup)         -- Setup -> Opportunity
    discover_opportunity(...)     -- full chain convenience

Gates (all deterministic, none invent evidence):

* A Signal requires an interpretable SUCCESS upstream observation.
* A Setup requires a directional read with present-and-usable quality
  (missing/INSUFFICIENT blocked; DEGRADED usable and visible) and a present
  horizon (never invented) -- enforced again by the Setup constructor.
* Expected behavior is deterministic candidate language: a directional read
  yields ``DIRECTIONAL_CONTINUATION_CANDIDATE``; the other expected-behavior
  values are reserved vocabulary for upstream evidence these inputs do not
  carry.
* Invalidation conditions are non-empty, deterministic, state/evidence
  descriptions of the thesis boundary -- never execution instructions.
* Thesis is a deterministic, explainable summary of the opportunity.

The pipeline is stateless and pure: identical inputs produce identical
stage objects; identities are caller-supplied; no wall clock, randomness,
network, database, filesystem, broker or execution behavior exists.
"""

from __future__ import annotations

from app.intelligence.contracts import (
    IntelligenceDirection,
    IntelligenceResult,
    IntelligenceStatus,
)
from app.opportunity.contracts import (
    ExpectedBehavior,
    Observation,
    ObservationKind,
    Opportunity,
    Setup,
    Signal,
    _directional,
)

#: Pipeline identity (deterministic; not a wall-clock artifact).
CALCULATION_ID = "opportunity.pipeline.v1"


def _require_directional_observation(observation: Observation) -> None:
    if observation.kind is not ObservationKind.INTELLIGENCE_RESULT:
        raise ValueError(
            f"unsupported observation kind {observation.kind.value!r} -- "
            "only INTELLIGENCE_RESULT observations are implemented today")


def _signal_explanation(upstream: IntelligenceResult) -> str:
    direction = upstream.direction.value if upstream.direction else "NON_DIRECTIONAL"
    return (f"{upstream.status.value} {direction} signal from "
            f"{upstream.calculation_id}")


def expected_behavior_for(direction: IntelligenceDirection) -> ExpectedBehavior:
    """Deterministic expected-behavior mapping (candidate language only).

    A directional read frames a directional-continuation candidate.  The
    remaining ExpectedBehavior values are reserved for upstream evidence
    (mean-reversion / breakout / volatility signatures) that the current
    Day-28 inputs do not carry -- they are never implied by a label.
    """
    if not _directional(direction):
        raise ValueError(
            "expected behavior requires a directional (BULLISH/BEARISH) read")
    return ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE


def invalidation_conditions_for(
    upstream: IntelligenceResult, direction: IntelligenceDirection,
) -> tuple[str, ...]:
    """Deterministic, observable, evidence-linked thesis-boundary
    conditions.  They describe when the opportunity's premise is no longer
    supported -- never stop-losses, cancellations, position management or
    broker actions."""
    return (
        f"upstream {upstream.calculation_id} no longer reports direction "
        f"{direction.value}",
        "upstream data quality becomes missing or INSUFFICIENT (below the "
        "usable floor)",
        f"the {len(upstream.evidence)} supporting upstream evidence rows are "
        "no longer emitted",
    )


def to_signal(observation: Observation, signal_id: str) -> Signal:
    """Observation -> Signal.

    Requires an interpretable SUCCESS upstream observation: PARTIAL /
    UNAVAILABLE / INVALID observations (including missing-quality ones)
    cannot become a Signal -- missing evidence never becomes a signal.
    """
    _require_directional_observation(observation)
    upstream = observation.upstream
    if upstream.status is not IntelligenceStatus.SUCCESS:
        raise ValueError(
            "a Signal requires an interpretable SUCCESS upstream observation "
            f"(status={upstream.status.value}) -- missing or insufficient "
            "evidence never becomes a signal")
    return Signal(
        signal_id=signal_id,
        observation_id=observation.observation_id,
        underlying=observation.underlying,
        expiry=observation.expiry,
        upstream=upstream,
        explanation=_signal_explanation(upstream),
    )


def to_setup(signal: Signal, setup_id: str) -> Setup:
    """Signal -> Setup.

    Requires a directional read (NEUTRAL / UNKNOWN / MIXED Signals can never
    form a directional setup) with present-and-usable quality and a present
    horizon -- never invented.  The Setup constructor re-enforces every
    gate.
    """
    upstream = signal.upstream
    if not _directional(signal.direction):
        raise ValueError(
            "a Setup requires a directional (BULLISH/BEARISH) signal -- "
            f"signal reports {signal.direction.value if signal.direction else None}")
    direction = signal.direction
    return Setup(
        setup_id=setup_id,
        signal_id=signal.signal_id,
        underlying=signal.underlying,
        expiry=signal.expiry,
        upstream=upstream,
        expected_behavior=expected_behavior_for(direction),
        invalidation_conditions=invalidation_conditions_for(upstream, direction),
    )


def to_opportunity(setup: Setup, opportunity_id: str) -> Opportunity:
    """Setup -> Opportunity (discovery ends here — nothing executes)."""
    direction = setup.direction
    return Opportunity(
        opportunity_id=opportunity_id,
        setup_id=setup.setup_id,
        underlying=setup.underlying,
        expiry=setup.expiry,
        upstream=setup.upstream,
        thesis=f"{direction.value} {setup.underlying} opportunity "
               f"({setup.expected_behavior.value}) from setup "
               f"{setup.setup_id} - {len(setup.evidence)} upstream evidence "
               f"rows from {setup.upstream.calculation_id}",
        expected_behavior=setup.expected_behavior,
        invalidation_conditions=setup.invalidation_conditions,
    )


def discover_opportunity(observation: Observation, signal_id: str,
                         setup_id: str, opportunity_id: str) -> Opportunity:
    """Full deterministic chain: Observation -> Signal -> Setup -> Opportunity.

    Raises ``ValueError`` at the first gate the observation cannot satisfy
    (the system fails safely rather than manufacturing an opportunity).
    """
    signal = to_signal(observation, signal_id)
    setup = to_setup(signal, setup_id)
    return to_opportunity(setup, opportunity_id)
