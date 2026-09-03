"""Day 24 — Expiry Intelligence + Market Event Detection tests (RED-phase
contract).

Proves the deterministic, broker-neutral expiry-context and state-transition
engine on the Day-19 Intelligence Contract, consuming only evidence available
through existing contracts (Day-20 StrikePositioning rows / compute_metrics,
Day-17 GEX totals + source, Day-15 annualized theta, Day-21/22/23 typed
outputs).

    expiry timestamp + concentration rows + GEX + theta + typed evidence
        -> deterministic expiry context (proximity / concentration / gamma /
           pinning / time-decay)
        -> explicit prior+current state transitions (events, never states)
        -> Day-19 IntelligenceResult(s)

Rules locked by these tests
---------------------------
1. An event is a TRANSITION, never a current state: it requires explicit
   prior AND current observations.  No previous observation => an explicit
   PARTIAL "initial state" condition — never a fabricated UNKNOWN -> X event.
2. Concentration, GEX sign, theta and pinning are measurements / evidence
   patterns — never directional meaning, support/resistance, pin certainty or
   market-maker intent.  Results are direction=NEUTRAL unless the caller
   supplies directional evidence (never inferred here).
3. Missing stays None (never zero); a measured 0.0 stays a legitimate zero
   (e.g. measured-zero GEX => NEUTRAL gamma context).
4. Day-12 quality preserved (identity) and gated (missing/INSUFFICIENT =>
   PARTIAL); Day-9 provenance preserved verbatim; never recomputed.
5. signal_strength != confidence != quality; horizon EXPIRY (chain-scoped,
   mirroring Days 20-23).
6. Deterministic, repeatable, pure: no wall clock / random / DB / network /
   filesystem / broker imports (AST-guarded).
7. Golden expectations are independent hand arithmetic.

Hand arithmetic
---------------
expiry = _REF + 5d => 5.0 days => NEAR (strength 0.6); +0.5d => AT_EXPIRY
(1.0); +10d => FAR (0.3); -1d => EXPIRED (0.0).
Rows (100: c1000 p200) (200: c400 p1800) (300: c500 p300):
  ce_share 1900/4200 = 0.45238...  pe_share 2300/4200 = 0.54761...
  top = put 1800 @200 => top_share 1800/4200 = 0.42857...  spot 250 =>
  spot_distance_top |200-250|/250 = 0.2.
Pinning candidate: AT_EXPIRY + top_share 1500/2300 = 0.65217... >= 0.2 +
spot 250.5 => |250-250.5|/250.5 = 0.001996 <= 0.02 => PINNING_CANDIDATE
(conf 0.70 without GEX, 0.85 with GEX).
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

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
from app.intelligence.levels import LevelState
from app.intelligence.positioning import PositioningClassification
from app.intelligence.institutional import ActivityPattern
from app.intelligence.expiry import (
    AT_EXPIRY_DAYS,
    CALCULATION_ID,
    EventType,
    ExpiryInput,
    ExpiryProximity,
    GammaContext,
    NEAR_EXPIRY_DAYS,
    PINNING_CONCENTRATION_FLOOR,
    PINNING_SPOT_BAND,
    PinningClassification,
    TimeDecayContext,
    classify_expiry,
    evaluate_expiry,
    evaluate_transitions,
)
from app.intelligence.positioning import StrikePositioning

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()
NIFTY = "NIFTY"
_DAY = timedelta(days=1)


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


def _row(strike: float, call_oi=None, put_oi=None) -> StrikePositioning:
    return StrikePositioning(strike=strike, call_oi=call_oi, put_oi=put_oi)


def _rows_a():
    """Golden chain (see module docstring)."""
    return (
        _row(100.0, 1_000, 200),
        _row(200.0, 400, 1_800),
        _row(300.0, 500, 300),
    )


def _inp(*, expiry_offset_days=5.0, expiry=_UNSET, spot=250.0, rows=_UNSET,
         gex=None, gex_source=None, theta=None, regime=None,
         positioning=None, level_state=None, institutional=None,
         conflict=None, quality=_UNSET, prov=_UNSET,
         chain_expiry="2026-09-24") -> ExpiryInput:
    if expiry is _UNSET:
        expiry = _REF + timedelta(days=expiry_offset_days)
    return ExpiryInput(
        underlying=NIFTY,
        expiry=chain_expiry,
        expiry_timestamp=expiry,
        spot=spot,
        rows=rows if rows is not _UNSET else (),
        gex=gex,
        gex_source=gex_source,
        theta_reference=theta,
        regime_label=regime,
        positioning=positioning,
        level_state=level_state,
        institutional_pattern=institutional,
        conflict=conflict,
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
        inp = _inp()
        assert inp.underlying == NIFTY
        assert inp.expiry_timestamp is not None

    def test_naive_reference_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            ExpiryInput(underlying=NIFTY, reference_timestamp=naive,
                        provenance=_prov(), quality=_quality())

    def test_naive_expiry_timestamp_rejected(self):
        naive = datetime(2026, 9, 8, 10, 0, 0)
        with pytest.raises(ValueError):
            ExpiryInput(underlying=NIFTY, reference_timestamp=_REF,
                        expiry_timestamp=naive, provenance=_prov(),
                        quality=_quality())

    def test_provenance_required(self):
        with pytest.raises(ValueError):
            ExpiryInput(underlying=NIFTY, reference_timestamp=_REF,
                        provenance=None, quality=_quality())

    def test_quality_type_checked(self):
        with pytest.raises(ValueError):
            ExpiryInput(underlying=NIFTY, reference_timestamp=_REF,
                        provenance=_prov(), quality=QualityState.EXCELLENT)

    def test_gex_source_requires_gex(self):
        with pytest.raises(ValueError):
            _inp(gex=None, gex_source="MODEL")

    def test_conflict_must_be_bool(self):
        with pytest.raises(ValueError):
            _inp(conflict="yes")

    def test_constants_documented(self):
        assert AT_EXPIRY_DAYS == 1.0
        assert NEAR_EXPIRY_DAYS == 7.0
        assert PINNING_CONCENTRATION_FLOOR == 0.20
        assert PINNING_SPOT_BAND == 0.02
        assert CALCULATION_ID == "intelligence.expiry_event.v1"


# ---------------------------------------------------------------------------
# 2. Expiry proximity context
# ---------------------------------------------------------------------------


class TestExpiryProximity:
    def test_near_expiry(self):
        r = evaluate_expiry(_inp(expiry_offset_days=5.0))
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.observation.metric_name == "expiry_intelligence"
        assert r.observation.value == pytest.approx(0.6, rel=1e-9)
        ctx = classify_expiry(_inp(expiry_offset_days=5.0))
        assert ctx.proximity is ExpiryProximity.NEAR

    def test_at_expiry(self):
        ctx = classify_expiry(_inp(expiry_offset_days=0.5))
        assert ctx.proximity is ExpiryProximity.AT_EXPIRY
        r = evaluate_expiry(_inp(expiry_offset_days=0.5))
        assert r.observation.value == pytest.approx(1.0, rel=1e-9)

    def test_far_expiry(self):
        ctx = classify_expiry(_inp(expiry_offset_days=10.0))
        assert ctx.proximity is ExpiryProximity.FAR
        assert evaluate_expiry(_inp(expiry_offset_days=10.0)).observation.value \
            == pytest.approx(0.3, rel=1e-9)

    def test_expired(self):
        ctx = classify_expiry(_inp(expiry_offset_days=-1.0))
        assert ctx.proximity is ExpiryProximity.EXPIRED
        r = evaluate_expiry(_inp(expiry_offset_days=-1.0))
        assert r.status is IntelligenceStatus.SUCCESS  # measured, not missing
        assert r.observation.value == 0.0

    def test_time_remaining_evidence_row(self):
        r = evaluate_expiry(_inp(expiry_offset_days=5.0))
        rows = {e.source_reference_id: e.value for e in r.evidence}
        assert rows.get("exp:NIFTY:2026-09-24:time_to_expiry_days") \
            == pytest.approx(5.0, rel=1e-9)

    def test_missing_expiry_timestamp_partial(self):
        r = evaluate_expiry(_inp(expiry=None, rows=_rows_a()))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "expiry_timestamp" for i in r.issues)

    def test_deterministic_repeatability(self):
        a = evaluate_expiry(_inp(expiry_offset_days=5.0))
        b = evaluate_expiry(_inp(expiry_offset_days=5.0))
        assert a == b
        assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# 3. Strike concentration (measurements only)
# ---------------------------------------------------------------------------


class TestConcentration:
    def test_golden_shares(self):
        r = evaluate_expiry(_inp(rows=_rows_a()))
        rows = {e.source_reference_id: e.value for e in r.evidence}
        assert rows["exp:NIFTY:2026-09-24:ce_share"] \
            == pytest.approx(1900.0 / 4200.0, rel=1e-9)
        assert rows["exp:NIFTY:2026-09-24:pe_share"] \
            == pytest.approx(2300.0 / 4200.0, rel=1e-9)
        assert rows["exp:NIFTY:2026-09-24:top_strike"] == pytest.approx(200.0)
        assert rows["exp:NIFTY:2026-09-24:top_share"] \
            == pytest.approx(1800.0 / 4200.0, rel=1e-9)
        assert rows["exp:NIFTY:2026-09-24:spot_distance_top"] \
            == pytest.approx(0.2, rel=1e-9)

    def test_balanced_concentration(self):
        rows = (_row(100.0, 500, 500), _row(200.0, 500, 500))
        r = evaluate_expiry(_inp(rows=rows))
        ev = {e.source_reference_id: e.value for e in r.evidence}
        assert ev["exp:NIFTY:2026-09-24:ce_share"] == pytest.approx(0.5)
        assert ev["exp:NIFTY:2026-09-24:pe_share"] == pytest.approx(0.5)

    def test_missing_oi_side_stays_missing(self):
        rows = (_row(100.0, call_oi=1_000), _row(200.0, call_oi=500))
        r = evaluate_expiry(_inp(rows=rows))
        ev = {e.source_reference_id: e.value for e in r.evidence}
        assert "exp:NIFTY:2026-09-24:pe_share" not in ev  # missing != zero
        assert ev["exp:NIFTY:2026-09-24:ce_share"] == pytest.approx(1.0)

    def test_concentration_never_directional(self):
        r = evaluate_expiry(_inp(rows=_rows_a()))
        assert r.direction is IntelligenceDirection.NEUTRAL
        assert not r.issues

    def test_concentration_never_level_claim(self):
        # no support/resistance/level vocabulary may leak from concentration
        r = evaluate_expiry(_inp(rows=_rows_a()))
        assert all("level" not in e.source_reference_id for e in r.evidence)
        assert all("support" not in e.source_reference_id for e in r.evidence)


# ---------------------------------------------------------------------------
# 4. GEX context (Day-17 convention preserved)
# ---------------------------------------------------------------------------


class TestGexContext:
    def test_positive_gex(self):
        ctx = classify_expiry(_inp(gex=500_000.0, gex_source="MODEL"))
        assert ctx.gamma_context is GammaContext.POSITIVE
        r = evaluate_expiry(_inp(gex=500_000.0, gex_source="MODEL"))
        ev = {e.source_reference_id: e.value for e in r.evidence}
        assert ev["exp:NIFTY:2026-09-24:gex:MODEL"] == pytest.approx(500_000.0)

    def test_negative_gex(self):
        ctx = classify_expiry(_inp(gex=-300_000.0, gex_source="BROKER"))
        assert ctx.gamma_context is GammaContext.NEGATIVE

    def test_measured_zero_gex_is_neutral(self):
        ctx = classify_expiry(_inp(gex=0.0, gex_source="MODEL"))
        assert ctx.gamma_context is GammaContext.NEUTRAL

    def test_missing_gex_unsupported(self):
        ctx = classify_expiry(_inp(gex=None))
        assert ctx.gamma_context is GammaContext.UNSUPPORTED
        r = evaluate_expiry(_inp(gex=None))
        assert not any("gex" in e.source_reference_id for e in r.evidence)

    def test_broker_model_source_preserved(self):
        r = evaluate_expiry(_inp(gex=300_000.0, gex_source="BROKER"))
        assert any("gex:BROKER" in e.source_reference_id for e in r.evidence)


# ---------------------------------------------------------------------------
# 5. Pinning pressure (evidence pattern, never certainty)
# ---------------------------------------------------------------------------


class TestPinning:
    def _candidate_rows(self):
        # top = put 1500 @250 of 2300 total => top_share 0.65217...
        return (_row(250.0, 500, 1_500), _row(300.0, 100, 200))

    def test_sufficient_evidence_candidate(self):
        ctx = classify_expiry(_inp(expiry_offset_days=0.5, spot=250.5,
                                   rows=self._candidate_rows()))
        assert ctx.pinning is PinningClassification.PINNING_CANDIDATE
        r = evaluate_expiry(_inp(expiry_offset_days=0.5, spot=250.5,
                                 rows=self._candidate_rows()))
        assert r.confidence == pytest.approx(0.70, rel=1e-9)  # no GEX
        assert any("pinning:PINNING_CANDIDATE" in e.source_reference_id
                   for e in r.evidence)

    def test_candidate_with_gex_corroboration(self):
        r = evaluate_expiry(_inp(expiry_offset_days=0.5, spot=250.5,
                                 rows=self._candidate_rows(),
                                 gex=100_000.0, gex_source="MODEL"))
        assert r.confidence == pytest.approx(0.85, rel=1e-9)

    def test_far_expiry_is_unsupported(self):
        ctx = classify_expiry(_inp(expiry_offset_days=10.0, spot=250.5,
                                   rows=self._candidate_rows()))
        assert ctx.pinning is PinningClassification.PINNING_UNSUPPORTED

    def test_concentration_alone_never_pinning(self):
        # high concentration but spot far from the dominant strike:
        # evidence-limited, never a candidate
        ctx = classify_expiry(_inp(expiry_offset_days=0.5, spot=300.0,
                                   rows=self._candidate_rows()))
        assert ctx.pinning is PinningClassification.PINNING_EVIDENCE
        assert ctx.pinning is not PinningClassification.PINNING_CANDIDATE

    def test_pinning_is_never_certainty_or_directional(self):
        r = evaluate_expiry(_inp(expiry_offset_days=0.5, spot=250.5,
                                 rows=self._candidate_rows()))
        assert r.direction is IntelligenceDirection.NEUTRAL
        text = str(r)
        assert "will pin" not in text
        assert "guaranteed" not in text


# ---------------------------------------------------------------------------
# 6. Time-decay context
# ---------------------------------------------------------------------------


class TestTimeDecay:
    def test_accelerating_near_expiry(self):
        ctx = classify_expiry(_inp(expiry_offset_days=0.5, theta=-2.5))
        assert ctx.time_decay is TimeDecayContext.ACCELERATING

    def test_normal_far_expiry(self):
        ctx = classify_expiry(_inp(expiry_offset_days=10.0, theta=-2.5))
        assert ctx.time_decay is TimeDecayContext.NORMAL

    def test_missing_theta_unsupported(self):
        ctx = classify_expiry(_inp(expiry_offset_days=0.5, theta=None))
        assert ctx.time_decay is TimeDecayContext.UNSUPPORTED

    def test_missing_expiry_unsupported_even_with_theta(self):
        ctx = classify_expiry(_inp(expiry=None, theta=-2.5))
        assert ctx.time_decay is TimeDecayContext.UNSUPPORTED

    def test_theta_alone_never_directional(self):
        r = evaluate_expiry(_inp(expiry_offset_days=0.5, theta=-2.5))
        assert r.direction is IntelligenceDirection.NEUTRAL


# ---------------------------------------------------------------------------
# 7. Event transitions (transitions only — never states)
# ---------------------------------------------------------------------------


class TestEventTransitions:
    def test_ranging_to_trending(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.TRENDING),
            _inp(regime=RegimeLabel.RANGING))
        assert len(events) == 1
        ev = events[0]
        assert ev.status is IntelligenceStatus.SUCCESS
        assert ev.observation.metric_name == EventType.REGIME_TRANSITION.value
        assert ev.signal_strength == pytest.approx(1.0, rel=1e-9)
        assert ev.confidence == pytest.approx(0.90, rel=1e-9)
        assert ev.direction is IntelligenceDirection.NEUTRAL

    def test_trending_to_ranging(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.RANGING),
            _inp(regime=RegimeLabel.TRENDING))
        assert events[0].observation.metric_name \
            == EventType.REGIME_TRANSITION.value

    def test_low_vol_to_high_vol(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.HIGH_VOLATILITY),
            _inp(regime=RegimeLabel.LOW_VOLATILITY))
        assert len(events) == 1
        assert events[0].observation.metric_name \
            == EventType.REGIME_TRANSITION.value

    def test_positioning_transition(self):
        events = evaluate_transitions(
            _inp(positioning=PositioningClassification.SHORT_BUILDUP),
            _inp(positioning=PositioningClassification.LONG_BUILDUP))
        assert len(events) == 1
        assert events[0].observation.metric_name \
            == EventType.POSITIONING_TRANSITION.value

    def test_level_transition(self):
        events = evaluate_transitions(
            _inp(level_state=LevelState.STATIC),
            _inp(level_state=LevelState.STRENGTHENING))
        assert len(events) == 1
        assert events[0].observation.metric_name == EventType.LEVEL_TRANSITION.value

    def test_institutional_transition(self):
        events = evaluate_transitions(
            _inp(institutional=ActivityPattern.OI_UNWINDING_CONFIRMED),
            _inp(institutional=ActivityPattern.OI_BUILDUP_CONFIRMED))
        assert len(events) == 1
        assert events[0].observation.metric_name \
            == EventType.INSTITUTIONAL_TRANSITION.value

    def test_expiry_proximity_transition(self):
        events = evaluate_transitions(
            _inp(expiry_offset_days=0.5),      # AT_EXPIRY
            _inp(expiry_offset_days=10.0))     # FAR
        assert len(events) == 1
        ev = events[0]
        assert ev.observation.metric_name \
            == EventType.EXPIRY_PROXIMITY_TRANSITION.value
        # ordinal distance: |0 - 2| / 2 = 1.0
        assert ev.signal_strength == pytest.approx(1.0, rel=1e-9)

    def test_gamma_context_transition(self):
        events = evaluate_transitions(
            _inp(gex=-100_000.0, gex_source="MODEL"),
            _inp(gex=100_000.0, gex_source="MODEL"))
        assert len(events) == 1
        assert events[0].observation.metric_name \
            == EventType.GAMMA_CONTEXT_TRANSITION.value

    def test_conflict_appearing_transition(self):
        events = evaluate_transitions(_inp(conflict=True), _inp(conflict=False))
        assert len(events) == 1
        assert events[0].observation.metric_name \
            == EventType.DIRECTIONAL_CONFLICT_TRANSITION.value

    def test_no_previous_state_is_explicit_not_fabricated(self):
        events = evaluate_transitions(_inp(regime=RegimeLabel.TRENDING))
        assert len(events) == 1
        r = events[0]
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_REQUIRED_INPUT
                   and i.field == "previous" for i in r.issues)
        assert r.direction is None

    def test_identical_state_is_no_transition(self):
        inp = _inp(regime=RegimeLabel.TRENDING)
        assert evaluate_transitions(inp, inp) == ()

    def test_unknown_previous_never_fabricates_event(self):
        # UNKNOWN -> TRENDING is not a meaningful transition
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.TRENDING),
            _inp(regime=RegimeLabel.UNKNOWN))
        assert events == ()

    def test_missing_current_field_is_no_event(self):
        events = evaluate_transitions(
            _inp(regime=None),
            _inp(regime=RegimeLabel.RANGING))
        assert events == ()

    def test_multiple_simultaneous_transitions_ordered(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.TRENDING,
                 positioning=PositioningClassification.SHORT_BUILDUP),
            _inp(regime=RegimeLabel.RANGING,
                 positioning=PositioningClassification.LONG_BUILDUP))
        names = [e.observation.metric_name for e in events]
        assert names == [EventType.REGIME_TRANSITION.value,
                         EventType.POSITIONING_TRANSITION.value]
        assert all(e.direction is IntelligenceDirection.NEUTRAL for e in events)

    def test_event_timestamps_preserved(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.TRENDING),
            _inp(regime=RegimeLabel.RANGING))
        ev = events[0]
        assert ev.reference_timestamp == _REF
        assert all(e.reference_timestamp == _REF for e in ev.evidence)

    def test_transition_evidence_has_prior_and_current_rows(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.TRENDING, expiry_offset_days=5.0),
            _inp(regime=RegimeLabel.RANGING, expiry_offset_days=10.0))
        ev = events[0]
        refs = [e.source_reference_id for e in ev.evidence]
        assert any("prior:time_to_expiry_days" in r for r in refs)
        assert any(":time_to_expiry_days" in r and "prior:" not in r
                   for r in refs)


# ---------------------------------------------------------------------------
# 8. Quality / provenance / statuses
# ---------------------------------------------------------------------------


class TestQualityProvenance:
    def test_missing_quality_partial(self):
        r = evaluate_expiry(_inp(expiry_offset_days=5.0, quality=None))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY
                   for i in r.issues)

    def test_insufficient_quality_partial(self):
        q = _quality(QualityState.INSUFFICIENT)
        r = evaluate_expiry(_inp(expiry_offset_days=5.0, quality=q))
        assert r.status is IntelligenceStatus.PARTIAL
        assert any(i.code is IntelligenceIssueCode.INSUFFICIENT_QUALITY
                   for i in r.issues)
        assert r.quality is q

    def test_exact_quality_instance_preserved(self):
        q = _quality(QualityState.GOOD)
        r = evaluate_expiry(_inp(expiry_offset_days=5.0, quality=q))
        assert r.quality is q

    def test_provenance_preserved_verbatim(self):
        prov = _prov()
        r = evaluate_expiry(_inp(expiry_offset_days=5.0, prov=prov))
        assert r.provenance == prov
        assert all(e.provenance == prov for e in r.evidence)

    def test_no_evidence_unavailable(self):
        r = evaluate_expiry(_inp(expiry=None, spot=None))
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert any(i.code is IntelligenceIssueCode.MISSING_EVIDENCE
                   for i in r.issues)
        assert not r.evidence

    def test_signal_strength_confidence_quality_separate(self):
        q = _quality()
        r = evaluate_expiry(_inp(expiry_offset_days=5.0, quality=q))
        assert r.signal_strength == pytest.approx(0.6, rel=1e-9)
        assert r.confidence == pytest.approx(0.90, rel=1e-9)
        assert r.quality is q
        assert r.signal_strength != r.confidence
        assert r.confidence != q.quality_score

    def test_serialization_round_trip(self):
        r = evaluate_expiry(_inp(expiry_offset_days=5.0, rows=_rows_a(),
                                 gex=100_000.0, gex_source="MODEL"))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_event_result_serialization(self):
        events = evaluate_transitions(
            _inp(regime=RegimeLabel.TRENDING),
            _inp(regime=RegimeLabel.RANGING))
        assert IntelligenceResult.from_dict(events[0].to_dict()) == events[0]


# ---------------------------------------------------------------------------
# 9. Purity (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "expiry.py"

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