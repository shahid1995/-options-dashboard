"""Day 21 — Dynamic Support/Resistance Intelligence Engine tests (RED-phase
contract).

Proves the deterministic levels engine on the Day-19 Intelligence Contract:

    Raw Day-20 strike rows -> chain context -> candidates (measured facts)
        -> derived level evidence (shares / activity / interaction)
        -> SUPPORT/RESISTANCE classification (typed layer)
        -> per-level Day-19 IntelligenceResult (positional, evidence-linked)

Rules locked by these tests
---------------------------
1. A high-OI strike is a measured concentration fact, NOT automatically a
   level.  Static concentration alone yields UNCLASSIFIED and never an
   emitted level claim.
2. SUPPORT requires significant PE-side concentration AND at least one
   corroborator (strengthening/active put ΔOI, put volume activity, price
   interaction, or put-heavy asymmetry).  RESISTANCE is the call-side mirror.
3. Dynamic states are distinct: STATIC / STRENGTHENING / WEAKENING /
   CONFIRMED_INTERACTION / CONFLICTED_INTERACTION / MIXED_EVIDENCE /
   INSUFFICIENT_EVIDENCE.  No historical touches or price reactions are ever
   fabricated.
4. level_strength != confidence != data quality; strength is a bounded
   equal-mean of PRESENT normalized components (missing component != 0);
   confidence is a documented completeness table; the exact Day-12
   QualityResult and Day-9 Provenance are preserved verbatim.
5. Balanced CE/PE evidence => MIXED_EVIDENCE / UNCLASSIFIED — never forced.
6. Nearby same-kind levels merge deterministically by strike distance
   (CLUSTER_STRIKE_DISTANCE, inclusive boundary); different kinds never merge.
7. Deterministic, repeatable, pure: no wall clock / random / DB / network /
   filesystem / broker imports (AST-guarded — the Day-14 glob covers only
   app/quant).
8. Golden expectations are independent hand arithmetic — never produced by
   calling the engine under test.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    IntelligenceDirection,
    IntelligenceIssueCode,
    IntelligenceResult,
    IntelligenceStatus,
)
from app.intelligence.positioning import StrikePositioning
from app.intelligence.levels import (
    CALCULATION_ID,
    CLUSTER_STRIKE_DISTANCE,
    CONCENTRATION_THRESHOLD,
    LevelInput,
    LevelKind,
    LevelState,
    build_clusters,
    classify_levels,
    derive_chain_context,
    evaluate_levels,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()


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


def _row(strike: float, call_oi=None, put_oi=None, call_d=None, put_d=None,
         call_vol=None, put_vol=None) -> StrikePositioning:
    return StrikePositioning(strike=strike, call_oi=call_oi, put_oi=put_oi,
                             call_oi_change=call_d, put_oi_change=put_d,
                             call_volume=call_vol, put_volume=put_vol)


def _inp(*, rows=None, spot=250.0, spot_change=-10.0, quality=_UNSET,
         prov=_UNSET, expiry="2026-09-24") -> LevelInput:
    return LevelInput(
        underlying="NIFTY",
        expiry=expiry,
        spot=spot,
        spot_change=spot_change,
        rows=rows if rows is not None else _golden_rows(),
        reference_timestamp=_REF,
        window_seconds=86400.0,
        provenance=prov if prov is not _UNSET else _prov(),
        quality=quality if quality is not _UNSET else _quality(),
    )


def _golden_rows():
    """Hand-arithmetic golden chain (spot 250, spot_change -10):

    strike | call_oi | put_oi | call_d | put_d | call_vol | put_vol
    100    | 1000    | 200    | +100   | +50   | 800      | 100
    200    | 400     | 1800   | -50    | +600  | 150      | 2000
    300    | 500     | 300    | +60    | -40   | 100      | 50
    400    | 200     | 150    | +10    | +20   | 40       | 30

    maxima: call_oi 1000 | put_oi 1800 | |call_d| 100 | |put_d| 600 |
            call_vol 800 | put_vol 2000
    """
    return (
        _row(100.0, 1_000, 200, 100, 50, 800, 100),
        _row(200.0, 400, 1_800, -50, 600, 150, 2_000),
        _row(300.0, 500, 300, 60, -40, 100, 50),
        _row(400.0, 200, 150, 10, 20, 40, 30),
    )


# ---------------------------------------------------------------------------
# 1. Input validation + chain context
# ---------------------------------------------------------------------------


class TestInputAndContext:
    def test_valid_input(self):
        inp = _inp()
        assert inp.underlying == "NIFTY"
        assert len(inp.rows) == 4

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            LevelInput(underlying="NIFTY", expiry="2026-09-24", spot=250.0,
                       spot_change=-10.0, rows=(_row(100.0),),
                       reference_timestamp=naive, window_seconds=1.0,
                       provenance=_prov(), quality=_quality())

    def test_provenance_required(self):
        with pytest.raises(ValueError):
            LevelInput(underlying="NIFTY", expiry="2026-09-24", spot=250.0,
                       spot_change=-10.0, rows=(_row(100.0),),
                       reference_timestamp=_REF, window_seconds=1.0,
                       provenance=None, quality=_quality())

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            _inp(quality=QualityState.EXCELLENT)

    def test_golden_chain_context(self):
        ctx = derive_chain_context(_inp())
        assert ctx.max_call_oi == pytest.approx(1_000.0)
        assert ctx.max_put_oi == pytest.approx(1_800.0)
        assert ctx.max_call_abs_delta == pytest.approx(100.0)
        assert ctx.max_put_abs_delta == pytest.approx(600.0)
        assert ctx.max_call_volume == pytest.approx(800.0)
        assert ctx.max_put_volume == pytest.approx(2_000.0)

    def test_missing_side_context_is_none(self):
        rows = (_row(100.0, call_oi=10.0),)
        ctx = derive_chain_context(_inp(rows=rows))
        assert ctx.max_call_oi == pytest.approx(10.0)
        assert ctx.max_put_oi is None

    def test_context_zero_max_yields_none_shares(self):
        rows = (_row(100.0, call_oi=0.0, put_oi=0.0),)
        ctx = derive_chain_context(_inp(rows=rows))
        assert ctx.max_call_oi == pytest.approx(0.0)

    def test_constants_documented(self):
        assert CONCENTRATION_THRESHOLD == 0.5
        assert CLUSTER_STRIKE_DISTANCE == 50.0
        assert CALCULATION_ID == "intelligence.levels.v1"


# ---------------------------------------------------------------------------
# 2. Golden classification (hand arithmetic)
# ---------------------------------------------------------------------------


class TestGoldenClassification:
    def test_strike_100_resistance(self):
        cl = classify_levels(_inp())
        by = {c.strike: c for c in cl}
        assert by[100.0].kind is LevelKind.RESISTANCE

    def test_strike_200_support(self):
        by = {c.strike: c for c in classify_levels(_inp())}
        assert by[200.0].kind is LevelKind.SUPPORT

    def test_strike_300_resistance(self):
        by = {c.strike: c for c in classify_levels(_inp())}
        assert by[300.0].kind is LevelKind.RESISTANCE

    def test_strike_400_insufficient(self):
        by = {c.strike: c for c in classify_levels(_inp())}
        assert by[400.0].kind is LevelKind.UNCLASSIFIED
        assert by[400.0].state is LevelState.INSUFFICIENT_EVIDENCE

    def test_strike_200_support_strength_golden(self):
        by = {c.strike: c for c in classify_levels(_inp())}
        # mean(put_share 1.0, |put_d| share 1.0, put_vol share 1.0,
        #      interaction confirm 1.0)
        assert by[200.0].strength == pytest.approx(1.0, rel=1e-9)

    def test_strike_300_resistance_strength_golden(self):
        by = {c.strike: c for c in classify_levels(_inp())}
        # mean(call_share 500/1000=0.5, |call_d| 60/100=0.6, call_vol 100/800=0.125)
        # = 1.225/3 (no price interaction: price is below the strike and
        # falling — not approach, not a resistance conflict)
        assert by[300.0].strength == pytest.approx(1.225 / 3.0, rel=1e-9)

    def test_deterministic_order_by_strike(self):
        strikes = [c.strike for c in classify_levels(_inp())]
        assert strikes == sorted(strikes)


# ---------------------------------------------------------------------------
# 3. Highest OI alone never classifies
# ---------------------------------------------------------------------------


class TestHighestOIGuard:
    def _static_only_rows(self):
        # Strike 100: by far the highest put OI in the chain, but ΔOI = 0
        # (measured no change), volume = 0, OI balanced call=put (no
        # asymmetry) and no price move.
        return (
            _row(100.0, call_oi=5_000, put_oi=5_000, call_d=0.0, put_d=0.0,
                 call_vol=0.0, put_vol=0.0),
            _row(200.0, call_oi=1_000, put_oi=1_000, call_d=0.0, put_d=0.0,
                 call_vol=0.0, put_vol=0.0),
        )

    def test_highest_oi_strike_is_unclassified(self):
        inp = _inp(rows=self._static_only_rows(), spot=150.0, spot_change=0.0)
        by = {c.strike: c for c in classify_levels(inp)}
        assert by[100.0].kind is LevelKind.UNCLASSIFIED
        assert by[100.0].state is LevelState.STATIC

    def test_highest_oi_alone_emits_no_level_result(self):
        inp = _inp(rows=self._static_only_rows(), spot=150.0, spot_change=0.0)
        assert evaluate_levels(inp) == ()

    def test_highest_oi_with_supporting_evidence_classifies(self):
        rows = (
            _row(100.0, call_oi=5_000, put_oi=5_000, call_d=0.0, put_d=500.0,
                 call_vol=0.0, put_vol=0.0),
            _row(200.0, call_oi=1_000, put_oi=1_000),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=150.0, spot_change=0.0))}
        assert by[100.0].kind is LevelKind.SUPPORT  # put ΔOI strengthening
        assert by[100.0].state is LevelState.STRENGTHENING


# ---------------------------------------------------------------------------
# 4. Dynamic states
# ---------------------------------------------------------------------------


class TestDynamicStates:
    def _support_rows(self, put_d, put_vol=None):
        return (
            _row(100.0, call_oi=500, put_oi=2_000, put_d=put_d,
                 put_vol=put_vol),
            _row(200.0, call_oi=400, put_oi=500, put_d=0.0),
        )

    def test_strengthening(self):
        by = {c.strike: c for c in classify_levels(
            _inp(rows=self._support_rows(put_d=400.0), spot_change=None))}
        assert by[100.0].kind is LevelKind.SUPPORT
        assert by[100.0].state is LevelState.STRENGTHENING

    def test_weakening(self):
        # active put unwinding (|Δ| >= activity share of the chain max)
        by = {c.strike: c for c in classify_levels(
            _inp(rows=self._support_rows(put_d=-400.0), spot_change=None))}
        assert by[100.0].kind is LevelKind.SUPPORT
        assert by[100.0].state is LevelState.WEAKENING

    def test_confirmed_interaction(self):
        # price at 250 falling toward support at 200 (approach from above)
        rows = (
            _row(200.0, call_oi=400, put_oi=1_800, put_d=100.0, put_vol=1_000),
            _row(400.0, call_oi=1_000, put_oi=100),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=250.0, spot_change=-10.0))}
        assert by[200.0].state is LevelState.CONFIRMED_INTERACTION

    def test_conflicted_interaction_support_break_below(self):
        # support at 300 but price (250) is BELOW it and still falling
        rows = (
            _row(300.0, call_oi=100, put_oi=2_000, put_d=200.0),
            _row(500.0, call_oi=50, put_oi=60),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=250.0, spot_change=-10.0))}
        assert by[300.0].kind is LevelKind.SUPPORT
        assert by[300.0].state is LevelState.CONFLICTED_INTERACTION

    def test_resistance_conflict_break_above(self):
        # resistance at 300 but price (350) is ABOVE it and still rising
        rows = (
            _row(300.0, call_oi=2_000, put_oi=100, call_d=200.0),
            _row(500.0, call_oi=100, put_oi=50),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=350.0, spot_change=10.0))}
        assert by[300.0].kind is LevelKind.RESISTANCE
        assert by[300.0].state is LevelState.CONFLICTED_INTERACTION

    def test_static_level_from_asymmetry_only(self):
        # corroboration only via put-heavy standing asymmetry, no Δ/vol/price
        rows = (
            _row(100.0, call_oi=100, put_oi=2_000, call_d=0.0, put_d=0.0,
                 call_vol=0.0, put_vol=0.0),
            _row(200.0, call_oi=60, put_oi=80),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=150.0, spot_change=0.0))}
        assert by[100.0].kind is LevelKind.SUPPORT
        assert by[100.0].state is LevelState.STATIC


# ---------------------------------------------------------------------------
# 5. Balanced / conflicting evidence
# ---------------------------------------------------------------------------


class TestBalancedEvidence:
    def test_balanced_ce_pe_is_unclassified(self):
        # both sides significant AND corroborated at the same strike
        rows = (
            _row(100.0, call_oi=1_000, put_oi=1_000, call_d=200.0, put_d=200.0,
                 call_vol=500.0, put_vol=500.0),
            _row(300.0, call_oi=100, put_oi=100),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=150.0, spot_change=10.0))}
        assert by[100.0].kind is LevelKind.UNCLASSIFIED
        assert by[100.0].state is LevelState.MIXED_EVIDENCE

    def test_balanced_strike_emits_no_level(self):
        rows = (
            _row(100.0, call_oi=1_000, put_oi=1_000, call_d=200.0, put_d=200.0),
            _row(300.0, call_oi=100, put_oi=100),
        )
        r = evaluate_levels(_inp(rows=rows, spot=150.0, spot_change=10.0))
        assert all(res.observation.metric_name != "level_strength"
                   for res in r) or r == ()
        assert all(getattr(res, "direction", None) is not None for res in r)


# ---------------------------------------------------------------------------
# 6. Missing-data behaviour
# ---------------------------------------------------------------------------


class TestMissingData:
    def test_missing_oi_side_shares_none(self):
        rows = (_row(100.0, call_oi=500, put_oi=None),)
        ctx = derive_chain_context(_inp(rows=rows))
        assert ctx.max_put_oi is None

    def test_missing_delta_does_not_fabricate_strengthening(self):
        rows = (
            _row(100.0, call_oi=500, put_oi=2_000, put_d=None, put_vol=None,
                 call_vol=None, call_d=None),
            _row(200.0, call_oi=60, put_oi=80),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=150.0, spot_change=0.0))}
        # equal call/put standing OI? no — put-heavy asymmetry corroborates
        # statically, but nothing dynamic exists: state STATIC at most, never
        # STRENGTHENING/WEAKENING from a missing Δ
        assert by[100.0].state is LevelState.STATIC
        assert by[100.0].kind is LevelKind.SUPPORT

    def test_missing_price_is_no_interaction(self):
        rows = (
            _row(200.0, call_oi=400, put_oi=1_800, put_d=100.0),
            _row(400.0, call_oi=1_000, put_oi=100),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=250.0, spot_change=None))}
        assert by[200.0].state is LevelState.STRENGTHENING
        # missing interaction is never confirmed/conflicted
        assert by[200.0].state not in (
            LevelState.CONFIRMED_INTERACTION, LevelState.CONFLICTED_INTERACTION)

    def test_missing_price_lowers_confidence_not_strength(self):
        rows = (
            _row(200.0, call_oi=400, put_oi=1_800, put_d=100.0),
            _row(400.0, call_oi=1_000, put_oi=100),
        )
        res = evaluate_levels(_inp(rows=rows, spot=250.0, spot_change=None))
        assert res
        assert all(r.confidence == pytest.approx(0.5) for r in res)

    def test_one_sided_call_chain(self):
        rows = (
            _row(100.0, call_oi=1_000, call_d=100.0, call_vol=800.0),
            _row(200.0, call_oi=500, call_d=0.0, call_vol=0.0),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=150.0, spot_change=10.0))}
        assert by[100.0].kind is LevelKind.RESISTANCE
        # no put side anywhere — no support claims possible
        assert all(c.kind is not LevelKind.SUPPORT for c in by.values())

    def test_zero_vs_missing(self):
        rows = (_row(100.0, call_oi=0.0, put_oi=0.0, call_d=0.0, put_d=0.0),)
        ctx = derive_chain_context(_inp(rows=rows))
        assert ctx.max_call_oi == 0.0  # measured zero
        cl = classify_levels(_inp(rows=rows, spot=100.0, spot_change=0.0))
        assert cl[0].kind is LevelKind.UNCLASSIFIED


# ---------------------------------------------------------------------------
# 7. Clustering
# ---------------------------------------------------------------------------


def _support_at(strike, put_oi, put_d, max_delta):
    """One support-level row whose put Δ is the chain max (share 1.0)."""
    return _row(strike, call_oi=100, put_oi=put_oi, put_d=put_d,
                call_vol=0.0, put_vol=0.0)


class TestClustering:
    def _two_supports(self, s1, s2, d1=400.0, d2=100.0):
        rows = (
            _support_at(s1, 2_000, d1, 400.0),
            _support_at(s2, 1_200, d2, 400.0),
        )
        return classify_levels(_inp(rows=rows, spot=min(s1, s2) - 10.0,
                                    spot_change=-5.0))

    def test_nearby_supports_cluster(self):
        by = {c.strike: c for c in self._two_supports(100.0, 130.0)}
        clusters = build_clusters(tuple(by.values()))
        assert len(clusters) == 1
        assert clusters[0].kind is LevelKind.SUPPORT
        assert clusters[0].min_strike == 100.0
        assert clusters[0].max_strike == 130.0

    def test_boundary_equal_to_threshold_clusters(self):
        by = {c.strike: c for c in self._two_supports(100.0, 150.0)}
        clusters = build_clusters(tuple(by.values()))
        assert len(clusters) == 1  # gap 50 == CLUSTER_STRIKE_DISTANCE (inclusive)

    def test_boundary_just_over_threshold_does_not_cluster(self):
        by = {c.strike: c for c in self._two_supports(100.0, 151.0)}
        clusters = build_clusters(tuple(by.values()))
        assert len(clusters) == 2

    def test_representative_is_strongest(self):
        by = {c.strike: c for c in self._two_supports(100.0, 130.0,
                                                      d1=100.0, d2=400.0)}
        clusters = build_clusters(tuple(by.values()))
        # strike 130 has |Δ| share 1.0 vs 0.25 at 100 → strongest
        assert clusters[0].representative_strike == 130.0

    def test_tie_breaks_to_lower_strike(self):
        rows = (
            _row(100.0, call_oi=100, put_oi=2_000, put_d=400.0,
                 call_vol=0.0, put_vol=0.0),
            _row(130.0, call_oi=100, put_oi=2_000, put_d=400.0,
                 call_vol=0.0, put_vol=0.0),
        )
        by = {c.strike: c for c in classify_levels(
            _inp(rows=rows, spot=90.0, spot_change=-5.0))}
        assert by[100.0].strength == by[130.0].strength
        clusters = build_clusters(tuple(by.values()))
        assert clusters[0].representative_strike == 100.0

    def test_different_kinds_never_merge(self):
        support = classify_levels(_inp(rows=(
            _support_at(100.0, 2_000, 400.0, 400.0),
            _row(130.0, call_oi=1_500, put_oi=100, call_d=300.0),
            _row(400.0, call_oi=100, put_oi=100),
        ), spot=90.0, spot_change=-5.0))
        by = {c.strike: c for c in support}
        clusters = build_clusters(tuple(by.values()))
        assert len(clusters) == 2
        kinds = {c.kind for c in clusters}
        assert kinds == {LevelKind.SUPPORT, LevelKind.RESISTANCE}


# ---------------------------------------------------------------------------
# 8. Interpretation envelope
# ---------------------------------------------------------------------------


class TestEvaluation:
    def test_multiple_level_results(self):
        results = evaluate_levels(_inp())
        assert len(results) == 3  # 100 R, 200 S, 300 R
        strikes = {r.observation.metric_name: r for r in results}
        assert results[0].observation.value == pytest.approx(1.0, rel=1e-9)

    def test_results_are_positional_not_directional(self):
        for r in evaluate_levels(_inp()):
            assert r.status is IntelligenceStatus.SUCCESS
            assert r.direction is IntelligenceDirection.NEUTRAL
            assert r.observation.metric_name == "level_strength"
            assert r.calculation_id == CALCULATION_ID

    def test_conflict_result_is_partial_with_issue(self):
        rows = (
            _row(300.0, call_oi=100, put_oi=2_000, put_d=200.0),
            _row(500.0, call_oi=50, put_oi=60),
        )
        results = evaluate_levels(_inp(rows=rows, spot=250.0, spot_change=-10.0))
        assert results
        conflict = results[0]
        assert conflict.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.PARTIAL_EVIDENCE
                   for i in conflict.issues)

    def test_exact_quality_preserved(self):
        q = _quality(QualityState.GOOD)
        results = evaluate_levels(_inp(quality=q))
        assert results
        assert all(r.quality is q for r in results)

    def test_insufficient_quality_state_gates_success(self):
        q = _quality(QualityState.INSUFFICIENT)
        results = evaluate_levels(_inp(quality=q))
        assert results
        for r in results:
            assert r.status is not IntelligenceStatus.SUCCESS
            assert any(i.code is IntelligenceIssueCode.INSUFFICIENT_QUALITY
                       for i in r.issues)
            assert r.quality is q

    def test_missing_quality_gates_success(self):
        results = evaluate_levels(_inp(quality=None))
        assert results
        for r in results:
            assert r.status is not IntelligenceStatus.SUCCESS
            assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY
                       for i in r.issues)

    def test_provenance_preserved_verbatim(self):
        prov = _prov()
        results = evaluate_levels(_inp(prov=prov))
        assert results
        assert all(r.provenance == prov for r in results)

    def test_evidence_present_per_level(self):
        results = evaluate_levels(_inp())
        for r in results:
            assert r.evidence
            assert all(e.value is not None for e in r.evidence)  # SUCCESS rule

    def test_deterministic_repeatability(self):
        a = evaluate_levels(_inp())
        b = evaluate_levels(_inp())
        assert a == b
        assert [r.to_dict() for r in a] == [r.to_dict() for r in b]

    def test_serialization_round_trip(self):
        for r in evaluate_levels(_inp()):
            assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_extreme_finite_values(self):
        rows = (
            _row(100.0, call_oi=1e12, put_oi=1e6, call_d=1e9),
            _row(200.0, call_oi=1e6, put_oi=1e6),
        )
        results = evaluate_levels(_inp(rows=rows, spot=150.0, spot_change=10.0))
        assert results
        for r in results:
            for v in (r.signal_strength, r.confidence):
                assert v is None or abs(v) <= 1.0
            assert all(e.value is not None for e in r.evidence)

    def test_no_secret_strings(self):
        for r in evaluate_levels(_inp()):
            s = str(r)
            assert "sk_live" not in s
            assert "access_token" not in s


# ---------------------------------------------------------------------------
# 9. Purity (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "levels.py"

    def test_no_clock_io_or_broker_imports(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib", "fastapi"}
        tree = ast.parse(self._MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today", "time",
                                              "sleep"}
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("app.brokers")
                assert not module.startswith("app.services")
                assert not module.startswith("app.routers")

    def test_no_wall_clock_tokens_in_module(self):
        text = self._MODULE.read_text(encoding="utf-8")
        for token in ("datetime.now", "datetime.utcnow", "time.time()",
                      "uuid", "random."):
            assert token not in text
