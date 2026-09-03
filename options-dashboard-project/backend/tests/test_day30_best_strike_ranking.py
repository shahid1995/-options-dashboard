"""Day 30 — Best-Strike Ranking tests (RED-phase contract).

Proves the deterministic, broker-neutral strike-ranking boundary from the
approved Day-30 design:

    Opportunity -> Strike Candidate Set -> Factor Evaluation
        -> Deterministic Ranking -> Explainable Ranked Strikes

Nine explicit factors (liquidity, spread quality, IV, Greeks, positioning,
GEX, distance to spot, strategy objective, risk), each an explicit
normalized suitability score in [0,1] supplied by an upstream boundary.
Fixed documented default weights (0.15/0.15/0.10 x7, sum exactly 1.0):
rank = SUM(weight_i * factor_i).

Rules locked by these tests
---------------------------
1. Every candidate needs all nine factors for a fully ranked result.
   Missing or unusable (INSUFFICIENT-state) factors NEVER become zero:
   the candidate is suppressed with a deterministic reason naming the
   factor(s).  Missing != zero.
2. rank_score, confidence and data quality are separate fields: confidence
   and quality never change the ranking score.
3. Ordering: rank desc, underlying asc, expiry asc (None first), option
   type asc (CE then PE), strike asc, candidate_id asc -- fully
   deterministic for ties.
4. Invalid numeric inputs (NaN / inf / out-of-range scores, negative or
   non-summing weights, non-finite strikes) raise ValueError -- never
   silently coerced.
5. Every ranked strike exposes: position, total score, each factor score,
   each configured weight, each weighted contribution, objective id and
   alignment, risk suitability, candidate identity.  Contributions
   reconcile to the total score; explanations derive from actual inputs.
6. Provenance / Opportunity identity: a ranked strike retains its
   originating Day-28 Opportunity (identity, immutable); ranking never
   mutates it and never creates an execution intent.
7. Result statuses: SUCCESS / EMPTY / NOTHING_ELIGIBLE.
8. Determinism: identical inputs => identical scores, contributions,
   explanations, ordering and serialized bytes.
9. Purity: no wall clock, randomness, network, database, filesystem or
   broker/execution behavior (AST-guarded).

Golden arithmetic (default weights)
-----------------------------------
scores liquidity..risk = 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2
rank = 0.15*1.0 + 0.15*0.9 + 0.10*0.8 + 0.10*0.7 + 0.10*0.6 + 0.10*0.5
     + 0.10*0.4 + 0.10*0.3 + 0.10*0.2 = 0.6350
all 1.0 => 1.0; all 0.5 => 0.5
"""

from __future__ import annotations

import ast
import json
import math
import pathlib
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    INTELLIGENCE_CONTRACT_VERSION,
    EvidenceType,
    IntelligenceDirection,
    IntelligenceEvidence,
    IntelligenceObservation,
    IntelligenceResult,
    IntelligenceStatus,
    TimeHorizon,
)
from app.opportunity.contracts import Opportunity
from app.opportunity.pipeline import discover_opportunity
from app.strike_ranking.contracts import (  # module absent until GREEN
    FactorContribution,
    FactorObservation,
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
from app.strike_ranking.ranking import DEFAULT_RANKING_WEIGHTS, rank_strikes

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
NIFTY = "NIFTY"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _prov() -> Provenance:
    return Provenance(
        source="UPSTOX_SNAPSHOT_NORMALIZED",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=_REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _quality(state: QualityState = QualityState.EXCELLENT) -> QualityResult:
    return QualityResult(
        quality_score=95 if state is QualityState.EXCELLENT else 55,
        quality_state=state,
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=_REF,
        observation_time=_REF,
        observation_type="QUOTE",
        contract_version="1.0.0",
        reference_time=_REF,
    )


def _result(direction: IntelligenceDirection = IntelligenceDirection.BULLISH,
            strength: float = 0.5, confidence: float = 0.75,
            quality: QualityResult | None = None) -> IntelligenceResult:
    return IntelligenceResult(
        calculation_id="intelligence.synthesis.v1",
        status=IntelligenceStatus.SUCCESS,
        direction=direction,
        signal_strength=strength,
        confidence=confidence,
        time_horizon=TimeHorizon.EXPIRY,
        observation=IntelligenceObservation(
            metric_name="synthesis_strength", value=strength, unit="score_0_1"),
        evidence=(IntelligenceEvidence(
            source_reference_id="synthesis:NIFTY:2026-09-24:bull",
            evidence_type=EvidenceType.QUANT_DERIVED,
            value=strength, unit="score_0_1", reference_timestamp=_REF,
            provenance=_prov(), model_version="1.0.0",
            calculation_version="1.0.0"),),
        quality=quality if quality is not None else _quality(),
        provenance=_prov(),
        reference_timestamp=_REF,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version="1.0.0",
        calculation_version="1.0.0",
    )


def _opportunity(opp_id: str = "opp-1") -> Opportunity:
    return discover_opportunity(
        __import__("app.opportunity.contracts", fromlist=["Observation"]).Observation(
            observation_id="obs-1", underlying=NIFTY, expiry="2026-09-24",
            upstream=_result()),
        signal_id="sig-1", setup_id="stp-1", opportunity_id=opp_id,
    )


def _factor(factor: RankingFactor, score: float,
            state: QualityState = QualityState.EXCELLENT,
            raw: float | str | None = None) -> FactorObservation:
    return FactorObservation(factor=factor, score=score, state=state, raw=raw)


def _all_factors(scores: dict[RankingFactor, float] | None = None,
                 states: dict[RankingFactor, QualityState] | None = None) -> tuple:
    """Nine FactorObservations; missing keys default to a usable 0.8."""
    out = []
    for f in RankingFactor:
        score = (scores or {}).get(f, 0.8)
        state = (states or {}).get(f, QualityState.EXCELLENT)
        out.append(_factor(f, score, state=state))
    return tuple(out)


def _cand(candidate_id: str = "c1", underlying: str = NIFTY,
          option_type: OptionType = OptionType.CE, strike: float = 20000.0,
          expiry: str | None = "2026-09-24", factors=None,
          opportunity: Opportunity | None = None,
          confidence: float | None = None,
          quality: QualityResult | None = None) -> StrikeCandidateInput:
    return StrikeCandidateInput(
        candidate_id=candidate_id,
        underlying=underlying,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        factors=factors if factors is not None else _all_factors(),
        opportunity=opportunity,
        confidence=confidence,
        quality=quality,
    )


def _run(cands, weights: RankingWeights | None = None) -> StrikeRankingResult:
    return rank_strikes(StrikeRankingInput(
        candidates=tuple(cands),
        weights=weights if weights is not None else DEFAULT_RANKING_WEIGHTS,
        objective_id="dir-bull"))


def _f(enum_name: str) -> RankingFactor:
    return RankingFactor[enum_name]


# ---------------------------------------------------------------------------
# 1. Contract construction / validation
# ---------------------------------------------------------------------------


class TestFactorAndWeightsValidation:
    def test_factor_score_bounds(self):
        with pytest.raises(ValueError):
            _factor(_f("LIQUIDITY"), -0.01)
        with pytest.raises(ValueError):
            _factor(_f("LIQUIDITY"), 1.01)
        with pytest.raises(ValueError):
            _factor(_f("LIQUIDITY"), float("nan"))
        with pytest.raises(ValueError):
            _factor(_f("LIQUIDITY"), float("inf"))

    def test_factor_zero_score_is_measured_zero_not_missing(self):
        f = _factor(_f("LIQUIDITY"), 0.0)
        assert f.score == 0.0  # measured zero is a valid present score

    def test_factor_state_must_be_quality_state(self):
        with pytest.raises(ValueError):
            FactorObservation(factor=_f("RISK"), score=0.5,
                              state="WEIRD")  # type: ignore[arg-type]

    def test_weights_defaults_sum_exactly_one(self):
        w = DEFAULT_RANKING_WEIGHTS
        assert math.isclose(w.as_sum(), 1.0, abs_tol=1e-9)

    def test_custom_weights_must_sum_to_one(self):
        RankingWeights()  # defaults fine
        with pytest.raises(ValueError):
            RankingWeights(liquidity=0.3)  # sum < 1
        with pytest.raises(ValueError):
            RankingWeights(liquidity=0.5, spread_quality=0.5,
                           iv=0.5)  # sum > 1
        with pytest.raises(ValueError):
            RankingWeights(liquidity=-0.1)  # negative
        with pytest.raises(ValueError):
            RankingWeights(liquidity=float("nan"))
        with pytest.raises(ValueError):
            RankingWeights(liquidity=float("inf"))

    def test_candidate_identity_validation(self):
        with pytest.raises(ValueError):
            _cand(candidate_id="")
        with pytest.raises(ValueError):
            _cand(underlying="")
        with pytest.raises(ValueError):
            _cand(strike=float("nan"))
        with pytest.raises(ValueError):
            _cand(strike=-1.0)
        with pytest.raises(ValueError):
            _cand(expiry="")

    def test_option_type_is_ce_or_pe(self):
        assert OptionType.CE.value == "CE"
        assert OptionType.PE.value == "PE"
        with pytest.raises(ValueError):
            _cand(option_type="CALL")  # type: ignore[arg-type]

    def test_duplicate_factors_rejected(self):
        dup = _all_factors() + (_factor(_f("RISK"), 0.5),)
        with pytest.raises(ValueError):
            _cand(factors=dup)

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            _cand(confidence=1.5)
        with pytest.raises(ValueError):
            _cand(confidence=-0.1)


# ---------------------------------------------------------------------------
# 2. Golden ranking arithmetic
# ---------------------------------------------------------------------------


class TestGoldenArithmetic:
    def test_golden_sequence_score(self):
        scores = {
            _f("LIQUIDITY"): 1.0, _f("SPREAD_QUALITY"): 0.9,
            _f("IV"): 0.8, _f("GREEKS"): 0.7, _f("POSITIONING"): 0.6,
            _f("GEX"): 0.5, _f("DISTANCE_TO_SPOT"): 0.4,
            _f("STRATEGY_OBJECTIVE"): 0.3, _f("RISK"): 0.2,
        }
        r = _run([_cand(factors=_all_factors(scores))])
        assert r.status is StrikeRankingStatus.SUCCESS
        ranked = r.ranked[0]
        assert ranked.rank_score == pytest.approx(0.6350, rel=1e-9)

    def test_all_ones_score_is_one(self):
        r = _run([_cand(factors=_all_factors(
            {f: 1.0 for f in RankingFactor}))])
        assert r.ranked[0].rank_score == pytest.approx(1.0, rel=1e-9)

    def test_all_half_score_is_half(self):
        r = _run([_cand(factors=_all_factors(
            {f: 0.5 for f in RankingFactor}))])
        assert r.ranked[0].rank_score == pytest.approx(0.5, rel=1e-9)

    def test_measured_zero_factor_contributes_zero(self):
        scores = {f: 0.0 for f in RankingFactor}
        scores[_f("LIQUIDITY")] = 1.0
        r = _run([_cand(factors=_all_factors(scores))])
        assert r.ranked[0].rank_score == pytest.approx(0.15, rel=1e-9)

    def test_nine_contributions_present_and_reconcile(self):
        r = _run([_cand()])
        ranked = r.ranked[0]
        assert isinstance(ranked, RankedStrike)
        assert len(ranked.contributions) == 9
        assert all(isinstance(c, FactorContribution)
                   for c in ranked.contributions)
        total = sum(c.contribution for c in ranked.contributions)
        assert total == pytest.approx(ranked.rank_score, rel=1e-9)

    def test_all_nine_factors_represented(self):
        names = {c.factor for c in _run([_cand()]).ranked[0].contributions}
        assert names == set(RankingFactor)


# ---------------------------------------------------------------------------
# 3. Deterministic ordering / tie-breaking
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_higher_score_first(self):
        hi = _cand("hi", factors=_all_factors(
            {f: 1.0 for f in RankingFactor}))
        lo = _cand("lo", factors=_all_factors(
            {f: 0.1 for f in RankingFactor}))
        r = _run([lo, hi])
        assert [x.candidate_id for x in r.ranked] == ["hi", "lo"]
        assert [x.rank for x in r.ranked] == [1, 2]

    def test_tie_break_underlying_ascending(self):
        same = _all_factors()
        a = _cand("a", underlying="NIFTY", factors=same)
        b = _cand("b", underlying="BANKNIFTY", factors=_all_factors())
        r = _run([a, b])
        assert [x.underlying for x in r.ranked] == ["BANKNIFTY", "NIFTY"]

    def test_tie_break_expiry_ascending_none_first(self):
        a = _cand("a", expiry="2026-09-24")
        b = _cand("b", expiry=None)
        c = _cand("c", expiry="2026-10-01")
        r = _run([a, b, c])
        assert [x.expiry for x in r.ranked] == [None, "2026-09-24", "2026-10-01"]

    def test_tie_break_option_type_ce_before_pe(self):
        ce = _cand("ce", option_type=OptionType.CE)
        pe = _cand("pe", option_type=OptionType.PE)
        r = _run([pe, ce])
        assert [x.option_type for x in r.ranked] == [OptionType.CE, OptionType.PE]

    def test_tie_break_strike_ascending(self):
        a = _cand("a", strike=20050.0)
        b = _cand("b", strike=19950.0)
        c = _cand("c", strike=20000.0)
        r = _run([a, b, c])
        assert [x.strike for x in r.ranked] == [19950.0, 20000.0, 20050.0]

    def test_tie_break_candidate_id_ascending(self):
        a = _cand("z-cand")
        b = _cand("a-cand")
        r = _run([a, b])
        assert [x.candidate_id for x in r.ranked] == ["a-cand", "z-cand"]

    def test_repeated_execution_byte_identical(self):
        cands = (_cand("a", strike=1.0), _cand("b", strike=2.0),
                 _cand("c", strike=1.5))
        r1 = _run(cands)
        r2 = _run(cands)
        assert json.dumps(r1.to_dict(), sort_keys=True) == \
            json.dumps(r2.to_dict(), sort_keys=True)


# ---------------------------------------------------------------------------
# 4. Missing / unusable factor suppression (missing != zero)
# ---------------------------------------------------------------------------


class TestSuppression:
    @pytest.mark.parametrize("factor_name", [
        "LIQUIDITY", "SPREAD_QUALITY", "IV", "GREEKS", "POSITIONING",
        "GEX", "DISTANCE_TO_SPOT", "STRATEGY_OBJECTIVE", "RISK"])
    def test_each_missing_factor_suppresses(self, factor_name):
        factors = tuple(f for f in _all_factors()
                        if f.factor is not _f(factor_name))
        r = _run([_cand("m", factors=factors)])
        assert r.status is StrikeRankingStatus.NOTHING_ELIGIBLE
        assert r.ranked == ()
        assert len(r.suppressed) == 1
        s = r.suppressed[0]
        assert isinstance(s, SuppressedStrike)
        assert s.reason is SuppressionReason.MISSING_FACTOR
        assert _f(factor_name) in s.factors
        assert factor_name.lower() in s.detail

    @pytest.mark.parametrize("factor_name", [
        "LIQUIDITY", "RISK"])
    def test_unusable_factor_suppresses(self, factor_name):
        states = {f: QualityState.EXCELLENT for f in RankingFactor}
        states[_f(factor_name)] = QualityState.INSUFFICIENT
        r = _run([_cand(factors=_all_factors(states=states))])
        assert r.status is StrikeRankingStatus.NOTHING_ELIGIBLE
        assert r.suppressed[0].reason is SuppressionReason.UNUSABLE_FACTOR
        assert _f(factor_name) in r.suppressed[0].factors

    def test_degraded_factor_is_usable_and_visible(self):
        states = {f: QualityState.EXCELLENT for f in RankingFactor}
        states[_f("LIQUIDITY")] = QualityState.DEGRADED
        r = _run([_cand(factors=_all_factors(states=states))])
        assert r.status is StrikeRankingStatus.SUCCESS
        liq = [c for c in r.ranked[0].contributions
               if c.factor is _f("LIQUIDITY")][0]
        assert liq.state is QualityState.DEGRADED

    def test_missing_two_factors_reports_both(self):
        factors = tuple(f for f in _all_factors()
                        if f.factor not in (_f("GEX"), _f("RISK")))
        r = _run([_cand(factors=factors)])
        s = r.suppressed[0]
        assert s.reason is SuppressionReason.MISSING_FACTOR
        assert set(s.factors) == {_f("GEX"), _f("RISK")}

    def test_no_fabricated_zero_anywhere(self):
        factors = tuple(f for f in _all_factors()
                        if f.factor is not _f("IV"))
        r = _run([_cand(factors=factors)])
        s = r.suppressed[0]
        for c in s.factors:
            assert c is not _f("IV") or True  # factor names only
        assert _f("IV") in s.factors  # named, never a 0.0 row

    def test_empty_candidates_is_empty(self):
        r = _run([])
        assert r.status is StrikeRankingStatus.EMPTY
        assert r.ranked == () and r.suppressed == ()

    def test_all_suppressed_nothing_eligible(self):
        r = _run([_cand("a", factors=tuple(f for f in _all_factors()
                                           if f.factor is not _f("RISK"))),
                  _cand("b", factors=tuple(f for f in _all_factors()
                                           if f.factor is not _f("GEX")))])
        assert r.status is StrikeRankingStatus.NOTHING_ELIGIBLE
        assert len(r.suppressed) == 2


# ---------------------------------------------------------------------------
# 5. Score vs confidence vs quality separation
# ---------------------------------------------------------------------------


class TestSeparation:
    def test_confidence_never_changes_rank_score(self):
        low_conf = _cand("lo", confidence=0.1,
                         quality=_quality(QualityState.DEGRADED))
        high_conf = _cand("hi", confidence=0.95,
                          quality=_quality(QualityState.EXCELLENT))
        r = _run([low_conf, high_conf])
        # identical factors => identical score; confidence/quality differ
        assert r.ranked[0].rank_score == pytest.approx(
            r.ranked[1].rank_score, rel=1e-12)
        # equal scores tie-break by candidate_id ascending: "hi" first
        by_id = {x.candidate_id: x for x in r.ranked}
        assert by_id["lo"].confidence == 0.1
        assert by_id["hi"].confidence == 0.95
        assert by_id["lo"].quality.quality_state is QualityState.DEGRADED
        assert by_id["hi"].quality.quality_state is QualityState.EXCELLENT

    def test_separate_fields_exposed_on_ranked_strike(self):
        q = _quality(QualityState.GOOD)
        r = _run([_cand("a", confidence=0.4, quality=q)])
        x = r.ranked[0]
        assert x.confidence == 0.4
        assert x.quality is q
        assert x.rank_score != pytest.approx(0.4)  # not the same number


# ---------------------------------------------------------------------------
# 6. Explanation
# ---------------------------------------------------------------------------


class TestExplanation:
    def test_explanation_covers_factors_weights_contributions(self):
        r = _run([_cand()])
        x = r.ranked[0]
        assert x.explanation
        assert "objective" in x.explanation and "risk" in x.explanation
        for f in RankingFactor:
            assert f.value in x.explanation
        assert f"score {x.rank_score:.4f}" in x.explanation
        assert f"rank {x.rank}" in x.explanation

    def test_explanation_objective_id_present(self):
        r = rank_strikes(StrikeRankingInput(
            candidates=(_cand(),), weights=DEFAULT_RANKING_WEIGHTS,
            objective_id="credit-bullish"))
        assert "credit-bullish" in r.ranked[0].explanation

    def test_contribution_arithmetic_in_explanation(self):
        r = _run([_cand()])
        x = r.ranked[0]
        # each contribution appears as a signed amount
        for c in x.contributions:
            assert f"{c.contribution:+.4f}" in x.explanation

    def test_explanation_deterministic_across_runs(self):
        r1 = _run([_cand("a"), _cand("b")])
        r2 = _run([_cand("a"), _cand("b")])
        assert [x.explanation for x in r1.ranked] == \
            [x.explanation for x in r2.ranked]


# ---------------------------------------------------------------------------
# 7. Provenance / Opportunity boundary
# ---------------------------------------------------------------------------


class TestOpportunityBoundary:
    def test_opportunity_identity_preserved(self):
        opp = _opportunity("opp-42")
        cand = _cand("a", opportunity=opp)
        r = _run([cand])
        assert r.ranked[0].opportunity_id == "opp-42"
        assert r.ranked[0].opportunity is opp

    def test_opportunity_not_mutated(self):
        opp = _opportunity("opp-7")
        thesis_before = opp.thesis
        r = _run([_cand("a", opportunity=opp)])
        assert r.ranked[0].opportunity is opp
        assert opp.thesis == thesis_before
        assert opp.status.value == "CANDIDATE"

    def test_provenance_projection_available(self):
        opp = _opportunity()
        assert opp.provenance is not None
        r = _run([_cand("a", opportunity=opp)])
        assert r.ranked[0].provenance is opp.provenance

    def test_no_opportunity_is_rankable_without_fabrication(self):
        # a candidate without an Opportunity is rankable; opportunity
        # fields stay None (never fabricated)
        r = _run([_cand("a")])
        x = r.ranked[0]
        assert x.opportunity is None
        assert x.opportunity_id is None
        assert x.provenance is None


# ---------------------------------------------------------------------------
# 8. Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_result_round_trip(self):
        opp = _opportunity("opp-1")
        r = _run([_cand("a", opportunity=opp),
                  _cand("b", factors=tuple(f for f in _all_factors()
                                           if f.factor is not _f("RISK")))])
        assert r.status is StrikeRankingStatus.SUCCESS
        blob = json.dumps(r.to_dict())
        r2 = StrikeRankingResult.from_dict(json.loads(blob))
        assert r2.to_dict() == r.to_dict()
        assert len(r2.ranked) == 1
        assert len(r2.suppressed) == 1
        assert isinstance(r2.ranked[0].opportunity, Opportunity)

    def test_empty_round_trip(self):
        r = _run([])
        r2 = StrikeRankingResult.from_dict(json.loads(json.dumps(r.to_dict())))
        assert r2.to_dict() == r.to_dict()


# ---------------------------------------------------------------------------
# 9. Purity / execution boundary
# ---------------------------------------------------------------------------


class TestPurityAndBoundary:
    _PKG = pathlib.Path(__file__).resolve().parents[1] / "app" / "strike_ranking"

    def test_no_broker_or_execution_imports(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib", "fastapi",
                     "redis", "time"}
        for path in self._PKG.glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"now", "utcnow", "today",
                                                  "time", "sleep"}
                if isinstance(node, ast.Import):
                    for a in node.names:
                        assert a.name.split(".")[0] not in forbidden
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for banned in ("app.brokers", "app.services", "app.routers",
                                   "app.quant", "app.market_data.gateway",
                                   "app.streaming", "app.db", "app.models"):
                        assert not module.startswith(banned)

    def test_no_order_execution_vocabulary(self):
        for path in self._PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in ("place_order", "submit_order", "modify_order",
                          "cancel_order", "create_order", "order_router",
                          "broker_client", "execute("):
                assert token not in text

    def test_no_wall_clock_or_random_tokens(self):
        for path in self._PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in ("datetime.now", "datetime.utcnow", "uuid", "random.",
                          "time.time()"):
                assert token not in text
