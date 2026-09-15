"""Day 30 — Deterministic best-strike ranking.

``rank_strikes(StrikeRankingInput) -> StrikeRankingResult`` implements the
approved Day-30 design:

* every factor is an explicit normalized suitability score in [0,1];
* ``rank_score = SUM(weight_i * factor_score_i)`` with the explicit
  ``RankingWeights`` (defaults sum to exactly 1.0 within the documented
  numeric tolerance), so the score is bounded to [0,1];
* a candidate is ranked only when all nine factors are present and usable
  (state != INSUFFICIENT) -- any missing or unusable factor suppresses it
  with a deterministic reason naming the factor(s); missing NEVER becomes
  a zero or a favorable/unfavorable numeric value;
* ordering: rank score descending, then underlying ascending, expiry
  ascending (None first), option type ascending (CE before PE), strike
  ascending, candidate_id ascending -- stable for identical scores;
* confidence and Day-12 quality are echoed separately and never change
  the ranking score;
* the originating Day-28 Opportunity identity/provenance is preserved by
  reference; ranking never mutates it;
* explanations are generated deterministically from the actual evaluated
  inputs (factor scores, weights, contributions, objective id, risk).

The module is pure: no wall clock, randomness, network, database,
filesystem, broker or execution behavior.
"""

from __future__ import annotations

from app.strike_ranking.contracts import (
    FactorContribution,
    OptionType,
    RankedStrike,
    RankingFactor,
    RankingWeights,
    StrikeCandidateInput,
    StrikeRankingInput,
    StrikeRankingResult,
    StrikeRankingStatus,
    SuppressedStrike,
    SuppressionReason,
)

#: The approved default weight set (0.15 liquidity + 0.15 spread quality
#: + 0.10 for each of the remaining seven factors; sum == 1.0).
DEFAULT_RANKING_WEIGHTS = RankingWeights()

_ALL_FACTORS: tuple[RankingFactor, ...] = tuple(RankingFactor)


def _missing_factors(candidate: StrikeCandidateInput) -> tuple[RankingFactor, ...]:
    present = {f.factor for f in candidate.factors}
    return tuple(f for f in _ALL_FACTORS if f not in present)


def _unusable_factors(candidate: StrikeCandidateInput) -> tuple[RankingFactor, ...]:
    return tuple(f.factor for f in candidate.factors
                 if not f.usable)


def _suppress(candidate: StrikeCandidateInput, missing: tuple[RankingFactor, ...],
              unusable: tuple[RankingFactor, ...]) -> SuppressedStrike:
    if missing:
        reason = SuppressionReason.MISSING_FACTOR
        factor_names = missing
        detail = ("candidate is missing required factor(s): "
                  + ", ".join(f.value for f in missing))
    else:
        reason = SuppressionReason.UNUSABLE_FACTOR
        factor_names = unusable
        detail = ("candidate factor(s) are unusable (INSUFFICIENT state): "
                  + ", ".join(f.value for f in unusable))
    return SuppressedStrike(
        candidate_id=candidate.candidate_id,
        underlying=candidate.underlying,
        option_type=candidate.option_type,
        strike=candidate.strike,
        expiry=candidate.expiry,
        reason=reason,
        factors=factor_names,
        detail=detail,
    )


def _build_explanation(position: int, rank_score: float,
                       contributions: tuple[FactorContribution, ...],
                       objective_id: str | None) -> str:
    parts = [f"rank {position}; score {rank_score:.4f}"]
    for c in contributions:
        parts.append(f"{c.factor.value} {c.score:.3f}x{c.weight:.3f}="
                     f"{c.contribution:+.4f}")
    if objective_id:
        parts.append(f"objective {objective_id}")
    risk = [c for c in contributions
            if c.factor is RankingFactor.RISK]
    if risk:
        parts.append(f"risk suitability {risk[0].score:.3f}")
    return "; ".join(parts)


def _sort_key(entry: RankedStrike) -> tuple:
    return (
        -entry.rank_score,
        entry.underlying,
        entry.expiry if entry.expiry is not None else "",
        list(OptionType).index(entry.option_type),
        entry.strike,
        entry.candidate_id,
    )


def _rank_candidate(candidate: StrikeCandidateInput,
                    weights: RankingWeights,
                    objective_id: str | None) -> RankedStrike:
    """Build the ranked strike for one fully eligible candidate."""
    by_factor = {f.factor: f for f in candidate.factors}
    contributions: list[FactorContribution] = []
    running = 0.0
    for factor in _ALL_FACTORS:
        obs = by_factor[factor]
        weight = weights.weight(factor)
        contribution = weight * obs.score
        running += contribution
        contributions.append(FactorContribution(
            factor=factor, score=obs.score, weight=weight,
            contribution=contribution, state=obs.state, raw=obs.raw,
            provenance=obs.provenance))
    # Position and explanation are assigned after sorting.
    return RankedStrike(
        candidate_id=candidate.candidate_id,
        underlying=candidate.underlying,
        option_type=candidate.option_type,
        strike=candidate.strike,
        expiry=candidate.expiry,
        rank=0,
        rank_score=running,
        contributions=tuple(contributions),
        explanation="",
        opportunity=candidate.opportunity,
        confidence=candidate.confidence,
        quality=candidate.quality,
    )


def _finish_explanation(entry: RankedStrike,
                        objective_id: str | None) -> RankedStrike:
    return RankedStrike(
        candidate_id=entry.candidate_id,
        underlying=entry.underlying,
        option_type=entry.option_type,
        strike=entry.strike,
        expiry=entry.expiry,
        rank=entry.rank,
        rank_score=entry.rank_score,
        contributions=entry.contributions,
        explanation=_build_explanation(entry.rank, entry.rank_score,
                                       entry.contributions, objective_id),
        opportunity=entry.opportunity,
        confidence=entry.confidence,
        quality=entry.quality,
    )


def rank_strikes(inp: StrikeRankingInput) -> StrikeRankingResult:
    """Rank all candidates; suppress ineligible ones.

    Deterministic: identical inputs produce identical ranked and
    suppressed tuples and byte-identical serialized results.
    """
    if not isinstance(inp, StrikeRankingInput):
        raise ValueError("rank_strikes requires a StrikeRankingInput")
    if not inp.candidates:
        return StrikeRankingResult(
            status=StrikeRankingStatus.EMPTY,
            ranked=(),
            suppressed=(),
            weights=inp.weights,
            objective_id=inp.objective_id,
        )

    ranked: list[RankedStrike] = []
    suppressed: list[SuppressedStrike] = []
    for candidate in inp.candidates:
        missing = _missing_factors(candidate)
        unusable = _unusable_factors(candidate)
        if missing or unusable:
            suppressed.append(_suppress(candidate, missing, unusable))
            continue
        ranked.append(_rank_candidate(candidate, inp.weights, inp.objective_id))

    ranked.sort(key=_sort_key)
    finalized: list[RankedStrike] = []
    for position, entry in enumerate(ranked, start=1):
        positioned = RankedStrike(
            candidate_id=entry.candidate_id,
            underlying=entry.underlying,
            option_type=entry.option_type,
            strike=entry.strike,
            expiry=entry.expiry,
            rank=position,
            rank_score=entry.rank_score,
            contributions=entry.contributions,
            explanation=entry.explanation,
            opportunity=entry.opportunity,
            confidence=entry.confidence,
            quality=entry.quality,
        )
        finalized.append(_finish_explanation(positioned, inp.objective_id))

    status = (StrikeRankingStatus.SUCCESS if finalized
              else StrikeRankingStatus.NOTHING_ELIGIBLE)
    return StrikeRankingResult(
        status=status,
        ranked=tuple(finalized),
        suppressed=tuple(suppressed),
        weights=inp.weights,
        objective_id=inp.objective_id,
    )
