"""Day 23 — Market Regime Engine tests (RED-phase contract).

Proves the deterministic, broker-neutral market-regime engine on the Day-19
Intelligence Contract, consuming the evidence surfaces of Days 20–22:

    price-window / volatility / positioning / institutional / level evidence
        -> deterministic regime classification (priority cascade)
        -> one Day-19 IntelligenceResult with MarketRegime attached

Rules locked by these tests
---------------------------
1. Regime vocabulary is the Day-19 RegimeLabel set exactly:
   TRENDING / RANGING / HIGH_VOLATILITY / LOW_VOLATILITY / RISK_ON /
   RISK_OFF / UNKNOWN.  No participant-identification claims.
2. TRENDING requires actual directional price-window evidence (>=3 same-sign
   nonzero moves); a single price observation is never a trend.  RANGING
   requires bounded alternating window evidence; "no trend" never becomes
   RANGING.  HIGH/LOW_VOLATILITY require an explicit volatility measure
   (never a threshold on a single price observation); missing volatility makes
   the vol regimes unreachable.  RISK_ON/RISK_OFF require price evidence plus
   >=1 corroborating source — positioning/institutional evidence alone is
   never a regime claim.  Insufficient evidence => UNKNOWN, never fabricated.
3. Opposing evidence (positioning/institutional/level vs price) => PARTIAL +
   MIXED + CONFLICTING_DIRECTION + regime UNKNOWN — conflicts outrank clean
   regimes and are never hidden.
4. signal_strength != confidence != quality; the exact Day-12 QualityResult
   and Day-9 Provenance are preserved; missing never becomes zero.
5. Deterministic, repeatable, pure: no wall clock / random / DB / network /
   filesystem / broker imports (AST-guarded).
6. Golden expectations are independent hand arithmetic.

Hand arithmetic
---------------
trend up  (10,8,12,9): net 39 gross 39 => TRENDING BULLISH strength 1.0 conf .90
trend down (-6,-9,-7,-4): net -26 => TRENDING BEARISH 1.0
trend+flat (5,0,7,6): nonzero (5,7,6) => TRENDING BULLISH 1.0
range (5,-4,6,-5): net 2 gross 20 => 0.10 <= 0.25 => RANGING NEUTRAL 0.90
range (8,-8,8,-8): net 0 => RANGING strength 1.0
range boundary (3,-3,1,1): net 2 gross 8 => 0.25 => RANGING (inclusive)
not range (3,-3,2,1): net 3 gross 9 => 0.333 > 0.25 => UNKNOWN
vol high 0.45 => HIGH_VOLATILITY strength 0.45 conf .85 direction UNKNOWN
vol low 0.08 => LOW_VOLATILITY strength 1 - 0.08/0.15 = 0.4666...
vol mid 0.20 => UNKNOWN; boundaries 0.30/0.15 exclusive => UNKNOWN
risk full: price up + LONG_BUILDUP + BULLISH institutional + constructive
  proximate support => RISK_ON BULLISH strength 3/3 = 1.0 conf .90
risk minimal: price up + LONG_BUILDUP only => RISK_ON strength 1/3 conf .75
risk off: price down + SHORT_BUILDUP + BEARISH institutional => RISK_OFF 2/3 .90
conflict: price up + BEARISH institutional => PARTIAL MIXED UNKNOWN .50
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
    RegimeLabel,
)
from app.intelligence.levels import LevelClassification, LevelKind, LevelState
from app.intelligence.positioning import PositioningClassification
from app.intelligence.regime import (
    CALCULATION_ID,
    HIGH_VOLATILITY_THRESHOLD,
    LOW_VOLATILITY_THRESHOLD,
    RANGING_MAX_NET_FRACTION,
    TREND_MIN_MOVES,
    RegimeInput,
    evaluate_regime,
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


def _inp(*, moves=(), spot=250.0, spot_change=10.0, volatility=None,
         positioning=_UNSET, inst_dir=None, inst_strength=None, levels=(),
         quality=_UNSET, prov=_UNSET, expiry="2026-09-24") -> RegimeInput:
    return RegimeInput(
        underlying=NIFTY,
        expiry=expiry,
        spot=spot,
        spot_change=spot_change,
        price_moves=tuple(moves),
        volatility=volatility,
        positioning=(None if positioning is _UNSET else positioning),
        institutional_direction=inst_dir,
        institutional_strength=inst_strength,
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
        inp = _inp(moves=(5.0, -4.0, 6.0))
        assert inp.underlying == NIFTY
        assert inp.price_moves == (5.0, -4.0, 6.0)

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            RegimeInput(underlying=NIFTY, reference_timestamp=naive,
                        provenance=_prov(), quality=_quality())

    def test_provenance_required(self):
        with pytest.raises(ValueError):
            RegimeInput(underlying=NIFTY, reference_timestamp=_REF,
                        provenance=None, quality=_quality())

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            RegimeInput(underlying=NIFTY, reference_timestamp=_REF,
                        provenance=_prov(), quality=QualityState.EXCELLENT)

    def test_non_finite_move_rejected(self):
        with pytest.raises(ValueError):
            _inp(moves=(1.0, float("inf")))

    def test_moves_must_be_tuple(self):
        with pytest.raises(ValueError):
            RegimeInput(underlying=NIFTY, reference_timestamp=_REF,
                        provenance=_prov(), quality=_quality(),
                        price_moves=[1.0, 2.0])

    def test_negative_volatility_rejected(self):
        with pytest.raises(ValueError):
            _inp(volatility=-0.1)

    def test_level_type_checked(self):
        with pytest.raises(ValueError):
            RegimeInput(underlying=NIFTY, reference_timestamp=_REF,
                        provenance=_prov(), quality=_quality(),
                        level_classifications=("x",))

    def test_institutional_strength_range(self):
        with pytest.raises(ValueError):
            _inp(inst_strength=1.5)

    def test_constants_documented(self):
        assert TREND_MIN_MOVES == 3
        assert RANGING_MAX_NET_FRACTION == 0.25
        assert HIGH_VOLATILITY_THRESHOLD == 0.30
        assert LOW_VOLATILITY_THRESHOLD == 0.15
        assert CALCULATION_ID == "intelligence.regime.v1"


# ---------------------------------------------------------------------------
# 2. TRENDING / RANGING (price-window evidence only)
# ---------------------------------------------------------------------------


class TestTrendingRanging:
    def test_trending_up(self):
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0)))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.regime is not None and r.regime.label is RegimeLabel.TRENDING
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_trending_down(self):
        r = evaluate_regime(_inp(moves=(-6.0, -9.0, -7.0, -4.0)))
        assert r.regime.label is RegimeLabel.TRENDING
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)

    def test_trend_with_measured_flat_inside(self):
        r = evaluate_regime(_inp(moves=(5.0, 0.0, 7.0, 6.0)))
        assert r.regime.label is RegimeLabel.TRENDING
        assert r.direction is IntelligenceDirection.BULLISH

    def test_two_moves_never_trend(self):
        r = evaluate_regime(_inp(moves=(5.0, 7.0)))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_single_move_never_trend(self):
        # one large price observation alone is never a trend (rule 1)
        r = evaluate_regime(_inp(moves=(-50.0,)))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_ranging(self):
        r = evaluate_regime(_inp(moves=(5.0, -4.0, 6.0, -5.0)))
        assert r.regime.label is RegimeLabel.RANGING
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert r.signal_strength == pytest.approx(0.90, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_ranging_perfectly_balanced(self):
        r = evaluate_regime(_inp(moves=(8.0, -8.0, 8.0, -8.0)))
        assert r.regime.label is RegimeLabel.RANGING
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)

    def test_ranging_boundary_inclusive(self):
        # net 2 / gross 8 = 0.25 exactly — RANGING (<=, inclusive)
        r = evaluate_regime(_inp(moves=(3.0, -3.0, 1.0, 1.0)))
        assert r.regime.label is RegimeLabel.RANGING

    def test_just_over_ranging_boundary_not_ranging(self):
        # net 3 / gross 9 = 0.333 > 0.25 — not ranging
        r = evaluate_regime(_inp(moves=(3.0, -3.0, 2.0, 1.0)))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_flat_price_is_not_ranging(self):
        # a measured flat price has no bounded-alternation evidence — UNKNOWN,
        # never RANGING from "no trend" (rule 2)
        r = evaluate_regime(_inp(moves=(), spot_change=0.0))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_mixed_sign_below_min_moves_not_ranging(self):
        r = evaluate_regime(_inp(moves=(3.0, -2.0)))
        assert r.regime.label is RegimeLabel.UNKNOWN


# ---------------------------------------------------------------------------
# 3. Volatility regimes (explicit measure required)
# ---------------------------------------------------------------------------


class TestVolatility:
    def test_high_volatility(self):
        r = evaluate_regime(_inp(volatility=0.45))
        assert r.regime.label is RegimeLabel.HIGH_VOLATILITY
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == pytest.approx(0.45, rel=1e-9)
        assert r.confidence == pytest.approx(0.85, rel=1e-9)

    def test_low_volatility(self):
        r = evaluate_regime(_inp(volatility=0.08))
        assert r.regime.label is RegimeLabel.LOW_VOLATILITY
        assert r.signal_strength == pytest.approx(1 - 0.08 / 0.15, rel=1e-9)
        assert r.confidence == pytest.approx(0.85, rel=1e-9)

    def test_mid_band_volatility_unknown(self):
        r = evaluate_regime(_inp(volatility=0.20))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_high_boundary_exclusive(self):
        # 0.30 exactly is NOT high volatility (strictly greater)
        r = evaluate_regime(_inp(volatility=HIGH_VOLATILITY_THRESHOLD))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_low_boundary_exclusive(self):
        # 0.15 exactly is NOT low volatility (strictly less)
        r = evaluate_regime(_inp(volatility=LOW_VOLATILITY_THRESHOLD))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_missing_volatility_never_vol_regime(self):
        # rule 3: no explicit volatility measure => never HIGH/LOW_VOLATILITY
        r = evaluate_regime(_inp(spot_change=10.0,
                                 positioning=PositioningClassification.LONG_BUILDUP,
                                 inst_dir=IntelligenceDirection.BULLISH))
        assert r.regime.label is RegimeLabel.RISK_ON

    def test_volatility_outranks_risk(self):
        r = evaluate_regime(_inp(volatility=0.45, spot_change=10.0,
                                 positioning=PositioningClassification.LONG_BUILDUP,
                                 inst_dir=IntelligenceDirection.BULLISH))
        assert r.regime.label is RegimeLabel.HIGH_VOLATILITY


# ---------------------------------------------------------------------------
# 4. RISK_ON / RISK_OFF (price evidence + corroboration required)
# ---------------------------------------------------------------------------


class TestRiskRegimes:
    def test_risk_on_full(self):
        lvl = _lvl(240.0, LevelKind.SUPPORT, LevelState.STRENGTHENING, 0.7)
        r = evaluate_regime(_inp(spot_change=10.0,
                                 positioning=PositioningClassification.LONG_BUILDUP,
                                 inst_dir=IntelligenceDirection.BULLISH,
                                 inst_strength=0.6, levels=(lvl,)))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.regime.label is RegimeLabel.RISK_ON
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)  # 3/3
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_risk_on_minimal_single_corroborator(self):
        r = evaluate_regime(_inp(spot_change=10.0,
                                 positioning=PositioningClassification.LONG_BUILDUP))
        assert r.regime.label is RegimeLabel.RISK_ON
        assert r.signal_strength == pytest.approx(1 / 3, rel=1e-9)
        assert r.confidence == pytest.approx(0.75, rel=1e-9)

    def test_risk_off(self):
        r = evaluate_regime(_inp(spot_change=-10.0,
                                 positioning=PositioningClassification.SHORT_BUILDUP,
                                 inst_dir=IntelligenceDirection.BEARISH))
        assert r.regime.label is RegimeLabel.RISK_OFF
        assert r.direction is IntelligenceDirection.BEARISH
        assert r.signal_strength == pytest.approx(2 / 3, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)

    def test_positioning_alone_is_never_regime(self):
        # rule 4: bullish positioning alone (no price evidence) => UNKNOWN
        r = evaluate_regime(_inp(spot_change=None,
                                 positioning=PositioningClassification.LONG_BUILDUP,
                                 inst_dir=IntelligenceDirection.BULLISH))
        assert r.regime.label is RegimeLabel.UNKNOWN

    def test_price_alone_is_unknown(self):
        r = evaluate_regime(_inp(spot_change=-50.0))
        assert r.regime.label is RegimeLabel.UNKNOWN


# ---------------------------------------------------------------------------
# 5. Conflicting evidence (never hidden)
# ---------------------------------------------------------------------------


class TestConflicts:
    def test_institutional_bearish_against_price(self):
        r = evaluate_regime(_inp(spot_change=10.0,
                                 inst_dir=IntelligenceDirection.BEARISH))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.regime.label is RegimeLabel.UNKNOWN
        assert any(i.code is IntelligenceIssueCode.CONFLICTING_DIRECTION
                   for i in r.issues)
        assert r.confidence == pytest.approx(0.50, rel=1e-9)

    def test_positioning_opposes_price(self):
        r = evaluate_regime(_inp(spot_change=10.0,
                                 positioning=PositioningClassification.SHORT_BUILDUP))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED

    def test_mixed_institutional_is_opposing(self):
        r = evaluate_regime(_inp(spot_change=10.0,
                                 inst_dir=IntelligenceDirection.MIXED))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED

    def test_level_breakdown_opposes_price(self):
        lvl = _lvl(200.0, LevelKind.SUPPORT, LevelState.CONFLICTED_INTERACTION, 0.6)
        r = evaluate_regime(_inp(spot_change=10.0, spot=190.0, levels=(lvl,)))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED

    def test_conflict_outranks_trend(self):
        # clean uptrend window BUT bearish institutional evidence => conflict
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0),
                                 inst_dir=IntelligenceDirection.BEARISH))
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.MIXED
        assert r.regime.label is RegimeLabel.UNKNOWN
        assert not any(e.value is None for e in r.evidence)


# ---------------------------------------------------------------------------
# 6. Missing data / statuses
# ---------------------------------------------------------------------------


class TestMissingData:
    def test_no_evidence_unavailable(self):
        r = evaluate_regime(_inp(spot=None, spot_change=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert any(i.code is IntelligenceIssueCode.MISSING_EVIDENCE
                   for i in r.issues)
        assert not r.evidence

    def test_unavailable_also_lists_missing_quality(self):
        r = evaluate_regime(_inp(spot=None, spot_change=None, quality=None))
        codes = {i.code for i in r.issues}
        assert IntelligenceIssueCode.MISSING_EVIDENCE in codes
        assert IntelligenceIssueCode.MISSING_QUALITY in codes

    def test_missing_quality_partial(self):
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0), quality=None))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY
                   for i in r.issues)
        assert r.direction is None

    def test_insufficient_quality_state_partial(self):
        q = _quality(QualityState.INSUFFICIENT)
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0), quality=q))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.INSUFFICIENT_QUALITY
                   for i in r.issues)
        assert r.quality is q

    def test_unknown_is_measured_not_fabricated(self):
        # evidence present, no classification: SUCCESS + UNKNOWN + strength 0
        r = evaluate_regime(_inp(moves=(5.0, 7.0)))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.regime.label is RegimeLabel.UNKNOWN
        assert r.direction is IntelligenceDirection.UNKNOWN
        assert r.signal_strength == 0.0
        assert r.confidence == pytest.approx(0.40, rel=1e-9)
        assert r.evidence  # measured assessment rests on present evidence

    def test_zero_moves_are_measured_flats(self):
        # a measured flat window (all-zero moves) is never trend/range
        # evidence and is never coerced into nonzero rows
        r = evaluate_regime(_inp(moves=(0.0, 0.0, 0.0)))
        assert r.regime.label is RegimeLabel.UNKNOWN
        assert all(e.value is not None for e in r.evidence)
        assert not any(e.source_reference_id.endswith("net_price_move")
                       for e in r.evidence)


# ---------------------------------------------------------------------------
# 7. Quality / provenance / separation
# ---------------------------------------------------------------------------


class TestQualityProvenance:
    def test_exact_quality_instance_preserved(self):
        q = _quality(QualityState.GOOD)
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0), quality=q))
        assert r.quality is q

    def test_provenance_preserved_verbatim(self):
        prov = _prov()
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0), prov=prov))
        assert r.provenance == prov
        assert all(e.provenance == prov for e in r.evidence)
        assert r.regime.source == CALCULATION_ID
        assert r.regime.reference_timestamp == _REF

    def test_signal_strength_confidence_quality_separate(self):
        q = _quality()
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0), quality=q))
        assert r.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)
        assert r.quality is q
        assert r.signal_strength != r.confidence
        assert r.confidence != r.quality.quality_score

    def test_regime_label_vocabulary_is_exact(self):
        from app.intelligence.contracts import RegimeLabel as RL
        labels = {r.regime.label for r in (
            evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0))),
            evaluate_regime(_inp(moves=(5.0, -4.0, 6.0, -5.0))),
            evaluate_regime(_inp(volatility=0.45)),
            evaluate_regime(_inp(volatility=0.08)),
            evaluate_regime(_inp(spot_change=10.0,
                                 positioning=PositioningClassification.LONG_BUILDUP)),
            evaluate_regime(_inp(moves=(5.0, 7.0))),
        )}
        assert labels <= {e.value for e in RL}

    def test_no_participant_identity_claims(self):
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0)))
        text = str(r)
        for token in ("FII", "DII", "market_maker", "institution is"):
            assert token not in text

    def test_no_fabricated_history_claims(self):
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0)))
        assert "history" not in str(r).lower()


# ---------------------------------------------------------------------------
# 8. Determinism / serialization
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_execution_identical(self):
        a = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0)))
        b = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0)))
        assert a == b
        assert a.to_dict() == b.to_dict()

    def test_serialization_round_trip_trend(self):
        r = evaluate_regime(_inp(moves=(10.0, 8.0, 12.0, 9.0)))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_serialization_round_trip_conflict(self):
        r = evaluate_regime(_inp(spot_change=10.0,
                                 inst_dir=IntelligenceDirection.BEARISH))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_serialization_round_trip_unavailable(self):
        r = evaluate_regime(_inp(spot=None, spot_change=None))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_extreme_finite_values_bounded(self):
        r = evaluate_regime(_inp(moves=(1e6, 9e5, 8e5), volatility=0.9))
        assert r.signal_strength is not None and r.signal_strength <= 1.0
        assert r.confidence is not None and r.confidence <= 1.0
        assert all(e.value is not None for e in r.evidence)


# ---------------------------------------------------------------------------
# 9. Purity (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "regime.py"

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