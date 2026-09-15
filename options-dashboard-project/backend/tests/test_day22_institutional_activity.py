"""Day 22 — Institutional-Like Activity Intelligence engine tests (RED-phase
contract).

Proves the deterministic, broker-neutral institutional-LIKE activity engine on
the Day-19 Intelligence Contract, consuming the canonical chain metrics of the
Day-20 positioning/flow engines and the Day-21 typed level-classification
surface:

    Day-20 chain metrics + Day-21 typed levels
        -> derived context (net ΔOI, flow, imbalance, delta/vega shifts)
        -> deterministic pattern cascade
        -> exactly one Day-19 IntelligenceResult per evaluation

Rules locked by these tests
---------------------------
1. INSTITUTIONAL_LIKE language only: outputs describe observable evidence
   patterns; the engine NEVER claims to identify institutions, market makers,
   banks, FII/DII or any specific participant.
2. Missing values stay None — never coerced to zero; a measured 0.0 is a
   legitimate zero.  SUCCESS rests only on present, finite evidence.
3. Exactly one deterministic result per evaluation (documented cascade):
   POSITION_FLOW_CONFLICT > OI_BUILDUP_CONFIRMED > OI_UNWINDING_CONFIRMED
   > VOLUME_IMBALANCE_FLOW > NO_PATTERN; conflicting evidence is PARTIAL +
   MIXED + CONFLICTING_DIRECTION, never forced bullish/bearish.
4. OI patterns require |net ΔOI| >= OI_ACTIVITY_FLOOR (200k contracts);
   volume-imbalance requires total volume >= VOLUME_ACTIVITY_FLOOR (200k) and
   |imbalance| >= IMBALANCE_THRESHOLD (0.5) — documented absolute scale
   references (no per-underlying baselines exist yet; no history fabricated).
5. signal_strength != confidence != data quality; the exact Day-12
   QualityResult instance and Day-9 Provenance are preserved.
6. Deterministic, repeatable, pure: no wall clock / random / DB / network /
   filesystem / broker imports (AST-guarded).
7. Golden expectations are independent hand arithmetic — never produced by
   calling the engine under test.

Hand arithmetic (fixtures)
--------------------------
OI floor 200k / vol floor 200k / |im| threshold 0.5 / strength refs 1,000,000:
  A  CD +400k PD +50k => net +450k (>= floor); price +30 (agreed)
        => OI_BUILDUP_CONFIRMED BULLISH strength 450k/1M = 0.45
  B  CD -300k PD -40k => net -340k; price +25
        => OI_UNWINDING_CONFIRMED BULLISH strength 0.34
  C  CD +300k PD +80k => net +380k; price -20
        => OI_BUILDUP_CONFIRMED BEARISH strength 0.38
  D  CD -250k PD -60k => net -310k; price -15
        => OI_UNWINDING_CONFIRMED BEARISH strength 0.31
  delta conflict: CDS +80k PDS -400k => ds -320k vs price +25
        => POSITION_FLOW_CONFLICT PARTIAL MIXED strength 0.32 conf 0.50
  vega conflict: VN +250k vs price -30 => PARTIAL MIXED strength 0.25 conf 0.50
  level conflict: proximate SUPPORT CONFLICTED_INTERACTION strength 0.7
        => PARTIAL MIXED strength 0.70 conf 0.50
  imbalance agreed: CV 800k PV 50k => tv 850k, im = 750/850 = 0.8823529...
        price +15 => VOLUME_IMBALANCE_FLOW BULLISH strength 0.8823529 conf 0.85
  imbalance opposed: same volumes, price -10
        => PARTIAL MIXED CONFLICTING_DIRECTION strength 0.8823529 conf 0.50
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
from app.intelligence.levels import LevelClassification, LevelKind, LevelState
from app.intelligence.institutional import (
    ActivityPattern,
    CALCULATION_ID,
    IMBALANCE_THRESHOLD,
    InstitutionalInput,
    OI_ACTIVITY_FLOOR,
    VOLUME_ACTIVITY_FLOOR,
    evaluate_institutional,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()
NIFTY = "NIFTY"


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


def _lvl(strike: float, kind: LevelKind, state: LevelState,
         strength: float | None = None) -> LevelClassification:
    return LevelClassification(strike=strike, kind=kind, state=state,
                               strength=strength)


def _inp(*, cd=None, pd=None, co=None, po=None, cv=None, pv=None,
         cds=None, pds=None, vn=None, levels=(),
         spot=250.0, spot_change=10.0, quality=_UNSET,
         prov=_UNSET, expiry="2026-09-24") -> InstitutionalInput:
    return InstitutionalInput(
        underlying=NIFTY,
        expiry=expiry,
        spot=spot,
        spot_change=spot_change,
        net_call_oi_change=cd,
        net_put_oi_change=pd,
        total_call_oi=co,
        total_put_oi=po,
        call_volume=cv,
        put_volume=pv,
        call_delta_shift=cds,
        put_delta_shift=pds,
        vega_shift_net=vn,
        level_classifications=tuple(levels),
        reference_timestamp=_REF,
        window_seconds=86400.0,
        provenance=prov if prov is not _UNSET else _prov(),
        quality=quality if quality is not _UNSET else _quality(),
    )


# ---------------------------------------------------------------------------
# 1. Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_valid_input(self):
        inp = _inp(cd=400_000.0, pd=50_000.0)
        assert inp.underlying == NIFTY
        assert inp.net_call_oi_change == 400_000.0

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            InstitutionalInput(
                underlying=NIFTY, net_call_oi_change=1.0,
                reference_timestamp=naive, provenance=_prov(),
                quality=_quality(),
            )

    def test_provenance_required(self):
        with pytest.raises(ValueError):
            InstitutionalInput(
                underlying=NIFTY, reference_timestamp=_REF,
                provenance=None, quality=_quality(),
            )

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            InstitutionalInput(
                underlying=NIFTY, reference_timestamp=_REF,
                provenance=_prov(), quality=QualityState.EXCELLENT,
            )

    def test_negative_volume_rejected(self):
        with pytest.raises(ValueError):
            _inp(cv=-1.0)

    def test_non_finite_rejected(self):
        with pytest.raises(ValueError):
            _inp(cd=float("inf"))

    def test_level_type_checked(self):
        with pytest.raises(ValueError):
            InstitutionalInput(
                underlying=NIFTY, reference_timestamp=_REF,
                provenance=_prov(), quality=_quality(),
                level_classifications=("not-a-level",),
            )

    def test_zero_volume_is_measured_zero(self):
        inp = _inp(cv=0.0, pv=0.0, cd=450_000.0, pd=50_000.0)
        assert inp.call_volume == 0.0


# ---------------------------------------------------------------------------
# 2. Golden pattern cascade (independent hand arithmetic)
# ---------------------------------------------------------------------------


class TestGoldenCascade:
    def test_long_buildup_agreed(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        cv=250_000.0, pv=60_000.0,
                                        spot_change=30.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.observation.metric_name == ActivityPattern.OI_BUILDUP_CONFIRMED.value
        assert r.observation.value == pytest.approx(0.45, rel=1e-9)
        assert r.signal_strength == pytest.approx(0.45, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)
        assert r.time_horizon is not None
        assert not r.issues

    def test_short_buildup_agreed(self):
        r = evaluate_institutional(_inp(cd=300_000.0, pd=80_000.0,
                                        spot_change=-20.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.observation.metric_name == ActivityPattern.OI_BUILDUP_CONFIRMED.value
        assert r.signal_strength == pytest.approx(0.38, rel=1e-9)

    def test_unwinding_agreed_price_up(self):
        r = evaluate_institutional(_inp(cd=-300_000.0, pd=-40_000.0,
                                        spot_change=25.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.observation.metric_name == ActivityPattern.OI_UNWINDING_CONFIRMED.value
        assert r.signal_strength == pytest.approx(0.34, rel=1e-9)

    def test_unwinding_agreed_price_down(self):
        r = evaluate_institutional(_inp(cd=-250_000.0, pd=-60_000.0,
                                        spot_change=-15.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.observation.metric_name == ActivityPattern.OI_UNWINDING_CONFIRMED.value
        assert r.signal_strength == pytest.approx(0.31, rel=1e-9)

    def test_buildup_below_floor_is_no_pattern(self):
        r = evaluate_institutional(_inp(cd=30_000.0, pd=10_000.0,
                                        cv=5_000.0, pv=3_000.0,
                                        spot_change=5.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert r.observation.metric_name == ActivityPattern.NO_PATTERN.value
        assert r.signal_strength == 0.0

    def test_measured_flat_price_is_no_pattern(self):
        # big OI shift but a measured flat price — no directional signal
        r = evaluate_institutional(_inp(cd=500_000.0, pd=50_000.0,
                                        spot_change=0.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert r.observation.metric_name == ActivityPattern.NO_PATTERN.value
        assert r.signal_strength == 0.0

    def test_pattern_constants_documented(self):
        assert OI_ACTIVITY_FLOOR == 200_000.0
        assert VOLUME_ACTIVITY_FLOOR == 200_000.0
        assert IMBALANCE_THRESHOLD == 0.5
        assert CALCULATION_ID == "intelligence.institutional_like.v1"


# ---------------------------------------------------------------------------
# 3. Confidence completeness
# ---------------------------------------------------------------------------


class TestConfidenceTable:
    def test_no_volume_lowers_confidence_not_strength(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.signal_strength == pytest.approx(0.45, rel=1e-9)
        assert r.confidence == pytest.approx(0.65, rel=1e-9)  # single-side

    def test_measured_zero_volume_is_present_volume(self):
        # CV/PV measured at 0.0 are present (not missing) -> full confidence
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        cv=0.0, pv=0.0, spot_change=30.0))
        assert r.confidence == pytest.approx(0.90, rel=1e-9)


# ---------------------------------------------------------------------------
# 4. Conflicts (never forced)
# ---------------------------------------------------------------------------


class TestConflicts:
    def test_delta_divergence_conflict(self):
        # OI below floor so only the cross-series divergence drives the read
        r = evaluate_institutional(_inp(cd=50_000.0, pd=40_000.0,
                                        cds=80_000.0, pds=-400_000.0,
                                        spot_change=25.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.observation.metric_name == ActivityPattern.POSITION_FLOW_CONFLICT.value
        assert r.signal_strength == pytest.approx(0.32, rel=1e-9)
        assert r.confidence == pytest.approx(0.50, rel=1e-9)
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)

    def test_vega_against_price_conflict(self):
        r = evaluate_institutional(_inp(cd=50_000.0, pd=40_000.0,
                                        vn=250_000.0, spot_change=-30.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.observation.metric_name == ActivityPattern.POSITION_FLOW_CONFLICT.value
        assert r.signal_strength == pytest.approx(0.25, rel=1e-9)
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)

    def test_level_breakdown_conflict(self):
        # proximate CONFLICTED_INTERACTION support (spot 190 below strike 200,
        # still falling) — a genuine Day-21 level conflict
        lvl = _lvl(200.0, LevelKind.SUPPORT,
                   LevelState.CONFLICTED_INTERACTION, 0.7)
        r = evaluate_institutional(_inp(cd=40_000.0, pd=20_000.0, levels=(lvl,),
                                        spot=190.0, spot_change=-15.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.observation.metric_name == ActivityPattern.POSITION_FLOW_CONFLICT.value
        assert r.signal_strength == pytest.approx(0.70, rel=1e-9)
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)

    def test_conflict_outranks_buildup(self):
        # huge bullish accumulation BUT delta shift opposes price -> conflict
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        cds=80_000.0, pds=-400_000.0,
                                        spot_change=30.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.observation.metric_name == ActivityPattern.POSITION_FLOW_CONFLICT.value


# ---------------------------------------------------------------------------
# 5. Volume imbalance
# ---------------------------------------------------------------------------


class TestVolumeImbalance:
    def test_imbalance_agreed(self):
        r = evaluate_institutional(_inp(cd=20_000.0, pd=20_000.0,
                                        cv=800_000.0, pv=50_000.0,
                                        spot_change=15.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.observation.metric_name == ActivityPattern.VOLUME_IMBALANCE_FLOW.value
        assert r.signal_strength == pytest.approx(750_000.0 / 850_000.0, rel=1e-9)
        assert r.confidence == pytest.approx(0.85, rel=1e-9)

    def test_imbalance_against_price_is_conflict(self):
        r = evaluate_institutional(_inp(cd=20_000.0, pd=20_000.0,
                                        cv=800_000.0, pv=50_000.0,
                                        spot_change=-10.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.observation.metric_name == ActivityPattern.VOLUME_IMBALANCE_FLOW.value
        assert r.signal_strength == pytest.approx(750_000.0 / 850_000.0, rel=1e-9)
        assert r.confidence == pytest.approx(0.50, rel=1e-9)
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)

    def test_imbalance_below_threshold_is_no_pattern(self):
        r = evaluate_institutional(_inp(cd=20_000.0, pd=20_000.0,
                                        cv=120_000.0, pv=100_000.0,
                                        spot_change=15.0))
        assert r.observation.metric_name == ActivityPattern.NO_PATTERN.value

    def test_low_total_volume_blocks_imbalance(self):
        # 0.8 imbalance but total volume 10k << 200k floor — meaningless ratio
        r = evaluate_institutional(_inp(cd=20_000.0, pd=20_000.0,
                                        cv=9_000.0, pv=1_000.0,
                                        spot_change=15.0))
        assert r.observation.metric_name == ActivityPattern.NO_PATTERN.value


# ---------------------------------------------------------------------------
# 6. Missing data behaviour
# ---------------------------------------------------------------------------


class TestMissingData:
    def test_no_evidence_at_all_unavailable(self):
        r = evaluate_institutional(_inp(spot=None, spot_change=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert any(i.code is IntelligenceIssueCode.MISSING_EVIDENCE
                   for i in r.issues)
        assert not r.evidence
        assert r.direction is None

    def test_unavailable_also_lists_missing_quality(self):
        r = evaluate_institutional(_inp(spot=None, spot_change=None,
                                        quality=None))
        codes = {i.code for i in r.issues}
        assert IntelligenceIssueCode.MISSING_EVIDENCE in codes
        assert IntelligenceIssueCode.MISSING_QUALITY in codes

    def test_missing_quality_is_partial(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0, quality=None))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY
                   for i in r.issues)
        assert r.direction is None
        assert r.evidence  # PARTIAL retains evidence

    def test_missing_price_is_partial(self):
        r = evaluate_institutional(_inp(cd=450_000.0, pd=50_000.0,
                                        spot_change=None))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "spot_change" for i in r.issues)
        assert r.direction is None

    def test_missing_oi_leg_is_partial(self):
        r = evaluate_institutional(_inp(cd=450_000.0, pd=None,
                                        spot_change=10.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "net_put_oi_change" for i in r.issues)
        assert r.direction is None

    def test_levels_only_is_partial(self):
        lvl = _lvl(240.0, LevelKind.SUPPORT, LevelState.STATIC, 0.55)
        r = evaluate_institutional(_inp(levels=(lvl,), spot=250.0,
                                        spot_change=10.0))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.evidence  # level rows are evidence; no OI/volume series
        assert r.direction is None

    def test_missing_volume_never_zeroes_oi_pattern(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == ActivityPattern.OI_BUILDUP_CONFIRMED.value

    def test_measured_zeros_are_evidence_not_missing(self):
        r = evaluate_institutional(_inp(cd=0.0, pd=0.0, cv=0.0, pv=0.0,
                                        spot_change=5.0))
        # measured no-change OI and zero volumes: no pattern, but SUCCESS
        # (measured) — evidence rows carry the measured zeros
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == ActivityPattern.NO_PATTERN.value
        assert any(e.value == 0.0 for e in r.evidence)


# ---------------------------------------------------------------------------
# 7. Quality / provenance / vocabulary
# ---------------------------------------------------------------------------


class TestQualityProvenanceVocab:
    def test_exact_quality_instance_preserved(self):
        q = _quality(QualityState.GOOD)
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0, quality=q))
        assert r.quality is q

    def test_provenance_preserved_verbatim(self):
        prov = _prov()
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0, prov=prov))
        assert r.provenance == prov
        assert all(e.provenance == prov for e in r.evidence)

    def test_signal_strength_confidence_quality_separate(self):
        q = _quality()
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        cv=250_000.0, pv=60_000.0,
                                        spot_change=30.0, quality=q))
        assert r.signal_strength == pytest.approx(0.45, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)
        assert r.quality is q
        assert r.signal_strength != r.confidence
        assert r.confidence != r.quality.quality_score

    def test_metric_names_are_pattern_vocabulary_only(self):
        vocab = {p.value for p in ActivityPattern}
        cases = [
            _inp(cd=400_000.0, pd=50_000.0, spot_change=30.0),
            _inp(cd=-300_000.0, pd=-40_000.0, spot_change=25.0),
            _inp(cd=50_000.0, pd=40_000.0, cds=80_000.0, pds=-400_000.0,
                 spot_change=25.0),
            _inp(cd=20_000.0, pd=20_000.0, cv=800_000.0, pv=50_000.0,
                 spot_change=15.0),
            _inp(cd=30_000.0, pd=10_000.0, cv=5_000.0, pv=3_000.0,
                 spot_change=5.0),
        ]
        for r in (evaluate_institutional(c) for c in cases):
            assert r.observation is None or r.observation.metric_name in vocab

    def test_no_participant_identity_claims(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0))
        text = str(r)
        for token in ("FII", "DII", "market_maker", "bank", "institution is",
                      "participant name"):
            assert token not in text

    def test_no_fabricated_history(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0))
        assert "history" not in str(r).lower()

    def test_evidence_references_present_per_result(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        cv=250_000.0, pv=60_000.0,
                                        spot_change=30.0))
        assert r.evidence
        assert all(e.value is not None for e in r.evidence)  # SUCCESS rule
        for e in r.evidence:
            assert e.source_reference_id.startswith("inst:NIFTY:")


# ---------------------------------------------------------------------------
# 8. Determinism / serialization
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_execution_identical(self):
        a = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0))
        b = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        spot_change=30.0))
        assert a == b
        assert a.to_dict() == b.to_dict()

    def test_serialization_round_trip(self):
        r = evaluate_institutional(_inp(cd=400_000.0, pd=50_000.0,
                                        cv=250_000.0, pv=60_000.0,
                                        spot_change=30.0))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_conflict_result_round_trip(self):
        r = evaluate_institutional(_inp(cd=50_000.0, pd=40_000.0,
                                        cds=80_000.0, pds=-400_000.0,
                                        spot_change=25.0))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_unavailable_result_round_trip(self):
        r = evaluate_institutional(_inp(spot=None, spot_change=None))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_extreme_finite_values_bounded(self):
        r = evaluate_institutional(_inp(cd=1e12, pd=5e5, cv=1e9, pv=1e6,
                                        spot_change=10.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.signal_strength is not None and r.signal_strength <= 1.0
        assert r.confidence is not None and r.confidence <= 1.0
        assert all(e.value is not None for e in r.evidence)


# ---------------------------------------------------------------------------
# 9. Purity (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "institutional.py"

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

    def test_no_participant_identity_in_vocabulary(self):
        text = self._MODULE.read_text(encoding="utf-8")
        assert "FII" not in text
        assert "DII" not in text
        assert "market_maker" not in text
