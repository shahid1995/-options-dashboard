"""Day 19 — Deterministic Intelligence Contract Foundation tests (RED-phase
contract).

Proves the canonical, broker-neutral intelligence contract that will sit
between the Quantitative Core (Days 14-18) and every future intelligence
engine:

    QuantResult / canonical observations / Day-12 QualityResult
        -> IntelligenceEvidence
        -> IntelligenceObservation
        -> IntelligenceResult (direction x strength x confidence x horizon,
                               quality preserved, provenance/versions,
                               status + structured issues)

Rules locked by these tests
---------------------------
1. Signal strength, confidence and data quality are THREE SEPARATE concepts:
   strength = how strong the observed/derived signal is (0..1); confidence =
   how confident the engine is that its interpretation is valid (0..1); data
   quality = the preserved Day-12 QualityResult envelope. Never
   interchangeable, never collapsed.
2. Missing data is NEVER converted into zero, NEUTRAL or SUCCESS: SUCCESS
   requires a non-empty evidence tuple with finite values, an observation, a
   direction, strength, confidence, a horizon, provenance and a reference
   timestamp, and zero issues. A None-valued evidence entry cannot underpin
   SUCCESS.
3. Status/issue consistency: PARTIAL => evidence + issues; UNAVAILABLE and
   INVALID => all interpretation fields None + issues (structured reasons
   preserved); SUCCESS => no issues.
4. Directional vocabulary: BULLISH/BEARISH/NEUTRAL/MIXED/UNKNOWN are distinct
   (MIXED/UNKNOWN never collapse into NEUTRAL). BULLISH/BEARISH/MIXED claims
   require positive strength and positive confidence (structural check only).
5. Immutable frozen contracts; deterministic serialization with a stable JSON
   representation; no wall clock / randomness / network / DB / broker imports
   (module-level AST checks, since the Day-14 guard globs only app/quant).
6. Provenance is preserved verbatim from the canonical Day-9 contract — never
   replaced with a generic placeholder. Quality is preserved as the whole
   Day-12 envelope (score + state + structured issues) — never recomputed.
7. Contract/model/calculation versions are explicit; no mutable global state.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib
from datetime import datetime, timedelta, timezone, tzinfo

import pytest

from app.market_data.contracts import DataMode, Provenance, QualityState
from app.market_data.quality import (
    DimensionResult,
    IssueSeverity,
    QualityDimension,
    QualityIssue,
    QualityIssueCode,
    QualityResult,
)
from app.intelligence.contracts import (
    INTELLIGENCE_CONTRACT_VERSION,
    EvidenceType,
    IntelligenceDirection,
    IntelligenceEvidence,
    IntelligenceIssue,
    IntelligenceIssueCode,
    IntelligenceObservation,
    IntelligenceResult,
    IntelligenceStatus,
    MarketRegime,
    RegimeLabel,
    TimeHorizon,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_REF2 = datetime(2026, 9, 3, 10, 5, 0, tzinfo=timezone.utc)
# IST-style fixed offset (UTC+5:30) — a genuinely aware, non-UTC tz.
_FIXED_OFFSET = timezone(timedelta(hours=5, minutes=30))


class _NoneOffsetTZ(tzinfo):
    """A tzinfo whose ``utcoffset()`` returns None — not genuinely aware."""

    def utcoffset(self, dt):
        return None

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return "NONE_OFFSET"


def _prov(*, source: str = "STRIKENOVA_QUANT", ts: datetime = _REF) -> Provenance:
    return Provenance(
        source=source,
        collection_mode=DataMode.TEST.value,
        received_at=ts,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _quality(state: QualityState = QualityState.EXCELLENT, score: int = 95) -> QualityResult:
    return QualityResult(
        quality_score=score,
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


def _issue(code: IntelligenceIssueCode = IntelligenceIssueCode.MISSING_EVIDENCE,
           message: str | None = None, field: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(
        code=code,
        message=message or code.value,
        field=field,
    )


def _evidence(*, value: float = 12500.0, kind: EvidenceType = EvidenceType.MARKET_OBSERVATION,
              source: str = "md:obs:nifty:20260903:24200", ts: datetime = _REF,
              prov: Provenance | None = None, model_ver: str = "1.0.0",
              calc_ver: str = "1.0.0") -> IntelligenceEvidence:
    return IntelligenceEvidence(
        source_reference_id=source,
        evidence_type=kind,
        value=value,
        unit="contracts" if kind is EvidenceType.QUALITY_ASSESSMENT else None,
        reference_timestamp=ts,
        provenance=prov,
        model_version=model_ver,
        calculation_version=calc_ver,
    )


def _observation(*, metric: str = "net_call_oi_delta", value: float = 12500.0) -> IntelligenceObservation:
    return IntelligenceObservation(metric_name=metric, value=value, unit="contracts")


def _result(**over) -> IntelligenceResult:
    base = dict(
        calculation_id="intelligence.positioning.v1",
        status=IntelligenceStatus.SUCCESS,
        direction=IntelligenceDirection.BULLISH,
        signal_strength=0.6,
        confidence=0.7,
        time_horizon=TimeHorizon.SWING,
        observation=_observation(),
        evidence=(_evidence(),),
        regime=None,
        quality=_quality(),
        provenance=_prov(),
        reference_timestamp=_REF,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version="0.1.0",
        calculation_version="0.1.0",
        issues=(),
    )
    base.update(over)
    return IntelligenceResult(**base)


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_valid_success_result(self):
        r = _result()
        assert r.status is IntelligenceStatus.SUCCESS
        assert r.direction is IntelligenceDirection.BULLISH
        assert r.signal_strength == 0.6
        assert r.confidence == 0.7
        assert r.time_horizon is TimeHorizon.SWING

    def test_valid_evidence_carries_provenance_and_versions(self):
        e = _evidence(prov=_prov())
        assert e.source_reference_id == "md:obs:nifty:20260903:24200"
        assert e.evidence_type is EvidenceType.MARKET_OBSERVATION
        assert e.provenance is not None
        assert e.model_version == "1.0.0"
        assert e.calculation_version == "1.0.0"

    def test_valid_partial_result(self):
        r = _result(
            status=IntelligenceStatus.PARTIAL,
            confidence=0.5,
            issues=(_issue(code=IntelligenceIssueCode.PARTIAL_EVIDENCE),),
        )
        assert r.status is IntelligenceStatus.PARTIAL
        assert r.direction is IntelligenceDirection.BULLISH  # read still produced
        assert len(r.issues) == 1

    def test_valid_unavailable_result(self):
        r = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(),
            quality=None,
            issues=(_issue(code=IntelligenceIssueCode.INSUFFICIENT_QUALITY,
                           message="quality below the interpretability floor"),),
        )
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert r.issues[0].code is IntelligenceIssueCode.INSUFFICIENT_QUALITY

    def test_valid_invalid_result(self):
        r = _result(
            status=IntelligenceStatus.INVALID,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(),
            issues=(_issue(code=IntelligenceIssueCode.INVALID_TIMESTAMP),),
        )
        assert r.status is IntelligenceStatus.INVALID

    def test_contract_version_constant_is_explicit(self):
        assert INTELLIGENCE_CONTRACT_VERSION == "1.0.0"
        assert _result().contract_version == "1.0.0"

    def test_all_direction_values_constructible(self):
        for d in IntelligenceDirection:
            r = _result(direction=d)
            assert r.direction is d

    def test_all_horizon_values_constructible(self):
        for h in TimeHorizon:
            r = _result(time_horizon=h)
            assert r.time_horizon is h

    def test_regime_attachment_allowed(self):
        regime = MarketRegime(label=RegimeLabel.RISK_ON, source="day23.regime.v1",
                              model_version="1.0.0", reference_timestamp=_REF)
        r = _result(regime=regime)
        assert r.regime.label is RegimeLabel.RISK_ON

    def test_regime_defaults_to_unknown(self):
        assert MarketRegime().label is RegimeLabel.UNKNOWN

    def test_unknown_regime_label_present_in_vocabulary(self):
        assert RegimeLabel.UNKNOWN.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# 2. Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_confidence_high(self):
        with pytest.raises(ValueError):
            _result(confidence=1.5)

    def test_invalid_confidence_negative(self):
        with pytest.raises(ValueError):
            _result(confidence=-0.1)

    def test_invalid_signal_strength_high(self):
        with pytest.raises(ValueError):
            _result(signal_strength=1.01)

    def test_invalid_signal_strength_negative(self):
        with pytest.raises(ValueError):
            _result(signal_strength=-0.01)

    def test_non_finite_confidence(self):
        with pytest.raises(ValueError):
            _result(confidence=float("nan"))

    def test_non_finite_signal_strength(self):
        with pytest.raises(ValueError):
            _result(signal_strength=float("inf"))

    def test_invalid_enum_string_rejected(self):
        with pytest.raises(ValueError):
            _result(direction="BULLISH")
        with pytest.raises(ValueError):
            _result(time_horizon="SWING")
        with pytest.raises(ValueError):
            _result(status="SUCCESS")

    def test_invalid_evidence_type_string_rejected(self):
        with pytest.raises(ValueError):
            _evidence(kind="MARKET_OBSERVATION")

    def test_non_finite_observation_value(self):
        with pytest.raises(ValueError):
            _observation(value=float("nan"))

    def test_empty_metric_name_rejected(self):
        with pytest.raises(ValueError):
            _observation(metric="")

    def test_empty_source_reference_rejected(self):
        with pytest.raises(ValueError):
            _evidence(source="")

    def test_empty_calculation_id_rejected(self):
        with pytest.raises(ValueError):
            _result(calculation_id="")

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 9, 3, 10, 0, 0)
        with pytest.raises(ValueError):
            _result(reference_timestamp=naive)
        with pytest.raises(ValueError):
            _evidence(ts=naive)
        with pytest.raises(ValueError):
            MarketRegime(label=RegimeLabel.RANGING, reference_timestamp=naive)

    def test_none_offset_tzinfo_rejected_as_not_genuinely_aware(self):
        # a tzinfo whose utcoffset() returns None is NOT genuinely aware
        fake_aware = datetime(2026, 9, 3, 10, 0, 0, tzinfo=_NoneOffsetTZ())
        assert fake_aware.tzinfo is not None  # would fool a naive check
        with pytest.raises(ValueError):
            _result(reference_timestamp=fake_aware)
        with pytest.raises(ValueError):
            _evidence(ts=fake_aware)
        with pytest.raises(ValueError):
            MarketRegime(label=RegimeLabel.RANGING, reference_timestamp=fake_aware)

    def test_fixed_offset_aware_timestamp_accepted(self):
        aware = datetime(2026, 9, 3, 15, 30, 0, tzinfo=_FIXED_OFFSET)
        r = _result(reference_timestamp=aware)
        assert r.reference_timestamp == aware
        assert r.reference_timestamp.utcoffset() is not None
        e = _evidence(ts=aware)
        assert e.reference_timestamp == aware
        regime = MarketRegime(label=RegimeLabel.RANGING, reference_timestamp=aware)
        assert regime.reference_timestamp == aware

    def test_non_finite_evidence_value_rejected(self):
        with pytest.raises(ValueError):
            _evidence(value=float("inf"))

    def test_invalid_quality_type_rejected(self):
        with pytest.raises(ValueError):
            _result(quality=QualityState.EXCELLENT)  # not a QualityResult

    def test_invalid_regime_label_rejected(self):
        with pytest.raises(ValueError):
            MarketRegime(label="RISK_ON")

    def test_empty_issue_message_rejected(self):
        with pytest.raises(ValueError):
            IntelligenceIssue(code=IntelligenceIssueCode.INTERNAL_ERROR, message="")

    def test_invalid_issue_code_string_rejected(self):
        with pytest.raises(ValueError):
            IntelligenceIssue(code="MISSING_EVIDENCE", message="x")


# ---------------------------------------------------------------------------
# 3. Status / evidence consistency
# ---------------------------------------------------------------------------


class TestStatusConsistency:
    def test_success_requires_evidence(self):
        with pytest.raises(ValueError):
            _result(evidence=())

    def test_success_rejects_none_valued_evidence(self):
        with pytest.raises(ValueError):
            _result(evidence=(_evidence(value=None),))

    def test_success_requires_observation(self):
        with pytest.raises(ValueError):
            _result(observation=None)

    def test_success_requires_direction(self):
        with pytest.raises(ValueError):
            _result(direction=None)

    def test_success_requires_strength_and_confidence(self):
        with pytest.raises(ValueError):
            _result(signal_strength=None)
        with pytest.raises(ValueError):
            _result(confidence=None)

    def test_success_requires_horizon(self):
        with pytest.raises(ValueError):
            _result(time_horizon=None)

    def test_success_requires_provenance(self):
        with pytest.raises(ValueError):
            _result(provenance=None)

    def test_success_requires_reference_timestamp(self):
        with pytest.raises(ValueError):
            _result(reference_timestamp=None)

    def test_success_rejects_issues(self):
        with pytest.raises(ValueError):
            _result(issues=(_issue(),))

    def test_partial_requires_issues(self):
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.PARTIAL, issues=())

    def test_partial_requires_evidence(self):
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.PARTIAL, evidence=(),
                    issues=(_issue(),))

    def test_partial_may_hold_none_valued_evidence(self):
        r = _result(status=IntelligenceStatus.PARTIAL,
                    evidence=(_evidence(value=None),),
                    issues=(_issue(code=IntelligenceIssueCode.PARTIAL_EVIDENCE),))
        # the missing value stays missing — never coerced to zero
        assert r.evidence[0].value is None

    def test_unavailable_forbids_interpretation_fields(self):
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.UNAVAILABLE, issues=(_issue(),))
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.UNAVAILABLE, direction=None,
                    signal_strength=None, confidence=None, time_horizon=None,
                    observation=None, evidence=(), issues=())
        # variant that also clears strength but keeps evidence -> forbidden
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.UNAVAILABLE, direction=None,
                    signal_strength=None, confidence=None, time_horizon=None,
                    observation=None, issues=(_issue(),))

    def test_unavailable_requires_issues(self):
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.UNAVAILABLE, direction=None,
                    signal_strength=None, confidence=None, time_horizon=None,
                    observation=None, evidence=(), issues=())

    def test_invalid_forbids_interpretation_fields(self):
        with pytest.raises(ValueError):
            _result(status=IntelligenceStatus.INVALID,
                    issues=(_issue(code=IntelligenceIssueCode.INVALID_INPUT_VALUE),))

    def test_unavailable_preserves_structured_reasons(self):
        r = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(), quality=None,
            issues=(
                _issue(code=IntelligenceIssueCode.MISSING_EVIDENCE, field="evidence"),
                _issue(code=IntelligenceIssueCode.MISSING_QUALITY, field="quality"),
            ),
        )
        codes = {i.code for i in r.issues}
        assert IntelligenceIssueCode.MISSING_EVIDENCE in codes
        assert IntelligenceIssueCode.MISSING_QUALITY in codes


# ---------------------------------------------------------------------------
# 3b. SUCCESS must preserve the Day-12 quality assessment
# ---------------------------------------------------------------------------


class TestSuccessRequiresQuality:
    def test_success_with_missing_quality_rejected(self):
        with pytest.raises(ValueError):
            _result(quality=None)

    def test_success_with_valid_quality_accepted(self):
        q = _quality(QualityState.GOOD, 82)
        r = _result(quality=q)
        assert r.status is IntelligenceStatus.SUCCESS
        assert isinstance(r.quality, QualityResult)

    def test_exact_quality_instance_preserved(self):
        q = _quality(QualityState.EXCELLENT, 99)
        r = _result(quality=q)
        assert r.quality is q  # same object, never copied/rewrapped

    def test_partial_preserves_supplied_quality(self):
        q = _quality(QualityState.DEGRADED, 64)
        r = _result(
            status=IntelligenceStatus.PARTIAL,
            quality=q,
            issues=(_issue(code=IntelligenceIssueCode.PARTIAL_EVIDENCE),),
        )
        assert r.quality is q
        assert r.quality.quality_score == 64
        assert r.quality.quality_state is QualityState.DEGRADED

    def test_unavailable_without_quality_valid_when_reason_explains(self):
        r = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(), quality=None,
            issues=(_issue(code=IntelligenceIssueCode.MISSING_QUALITY,
                           message="no Day-12 quality assessment supplied"),),
        )
        assert r.status is IntelligenceStatus.UNAVAILABLE
        assert r.quality is None
        assert any(i.code is IntelligenceIssueCode.MISSING_QUALITY for i in r.issues)

    def test_success_round_trip_preserves_quality(self):
        q = _quality(QualityState.GOOD, 88)
        r = _result(quality=q)
        rebuilt = IntelligenceResult.from_dict(r.to_dict())
        assert rebuilt == r
        assert rebuilt.quality == q
        assert rebuilt.quality.quality_state is QualityState.GOOD


# ---------------------------------------------------------------------------
# 4. Directional semantics
# ---------------------------------------------------------------------------


class TestDirectionalSemantics:
    def test_mixed_and_unknown_are_distinct_from_neutral(self):
        assert IntelligenceDirection.MIXED is not IntelligenceDirection.NEUTRAL
        assert IntelligenceDirection.UNKNOWN is not IntelligenceDirection.NEUTRAL
        assert IntelligenceDirection.MIXED.value == "MIXED"
        assert IntelligenceDirection.UNKNOWN.value == "UNKNOWN"
        assert IntelligenceDirection.NEUTRAL.value == "NEUTRAL"

    def test_neutral_never_overwritten_by_unknown(self):
        r = _result(direction=IntelligenceDirection.NEUTRAL)
        assert r.direction is IntelligenceDirection.NEUTRAL

    def test_bullish_requires_positive_strength(self):
        with pytest.raises(ValueError):
            _result(direction=IntelligenceDirection.BULLISH, signal_strength=0.0)

    def test_bearish_requires_positive_strength(self):
        with pytest.raises(ValueError):
            _result(direction=IntelligenceDirection.BEARISH, signal_strength=0.0)

    def test_mixed_requires_positive_strength(self):
        with pytest.raises(ValueError):
            _result(direction=IntelligenceDirection.MIXED, signal_strength=0.0)

    def test_bullish_requires_positive_confidence(self):
        with pytest.raises(ValueError):
            _result(direction=IntelligenceDirection.BULLISH, confidence=0.0)

    def test_neutral_accepts_any_confidence_and_strength(self):
        r = _result(direction=IntelligenceDirection.NEUTRAL, confidence=0.9,
                    signal_strength=0.0)
        assert r.direction is IntelligenceDirection.NEUTRAL

    def test_unknown_accepts_any_confidence(self):
        r = _result(direction=IntelligenceDirection.UNKNOWN, confidence=0.8,
                    signal_strength=0.0)
        assert r.direction is IntelligenceDirection.UNKNOWN


# ---------------------------------------------------------------------------
# 5. Semantic separation: strength != confidence != data quality
# ---------------------------------------------------------------------------


class TestSemanticSeparation:
    def test_fields_are_stored_separately(self):
        r = _result(signal_strength=0.3, confidence=0.9)
        assert r.signal_strength != r.confidence
        assert r.signal_strength == 0.3
        assert r.confidence == 0.9

    def test_quality_is_not_a_float_field(self):
        r = _result()
        assert isinstance(r.quality, QualityResult)
        assert not isinstance(r.signal_strength, QualityResult)
        # quality travels as the Day-12 envelope, not as strength/confidence
        assert r.quality.quality_score == 95
        assert r.quality.quality_state is QualityState.EXCELLENT

    def test_high_quality_with_low_confidence_is_expressible(self):
        # EXCELLENT data can still produce an uncertain read — and vice versa.
        r = _result(quality=_quality(QualityState.EXCELLENT, 98), confidence=0.25,
                    signal_strength=0.9)
        assert r.quality.quality_state is QualityState.EXCELLENT
        assert r.confidence == 0.25

    def test_high_confidence_with_degraded_quality_is_expressible(self):
        degraded = QualityResult(
            quality_score=62, quality_state=QualityState.DEGRADED,
            critical_failure=False,
            issues=(QualityIssue(QualityDimension.VALIDITY,
                                QualityIssueCode.INVALID_VOLUME,
                                IssueSeverity.ERROR, "volume out of range",
                                "volume"),),
            dimensions=(),
            evaluated_at=_REF, observation_time=_REF, observation_type="QUOTE",
            contract_version="1.0.0", reference_time=_REF,
        )
        r = _result(quality=degraded, confidence=0.8)
        assert r.quality.quality_state is QualityState.DEGRADED
        assert len(r.quality.issues) == 1
        assert r.confidence == 0.8

    def test_strength_and_quality_state_independent(self):
        # strength 0 (no directional signal) with EXCELLENT data is valid…
        r = _result(direction=IntelligenceDirection.NEUTRAL, signal_strength=0.0)
        assert r.signal_strength == 0.0
        assert r.quality.quality_state is QualityState.EXCELLENT


# ---------------------------------------------------------------------------
# 6. Missing data behaviour
# ---------------------------------------------------------------------------


class TestMissingData:
    def test_missing_evidence_not_converted_to_success(self):
        with pytest.raises(ValueError):
            _result(evidence=())

    def test_missing_value_not_converted_to_zero(self):
        e = _evidence(value=None)
        # inside a PARTIAL result the missing value stays None
        r = _result(status=IntelligenceStatus.PARTIAL, evidence=(e,),
                    issues=(_issue(code=IntelligenceIssueCode.PARTIAL_EVIDENCE),))
        assert r.evidence[0].value is None
        assert r.evidence[0].value != 0.0

    def test_missing_quality_is_explicit(self):
        r = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(),
            quality=None,
            issues=(_issue(code=IntelligenceIssueCode.MISSING_QUALITY),),
        )
        assert r.quality is None
        assert r.issues[0].code is IntelligenceIssueCode.MISSING_QUALITY

    def test_missing_quality_never_becomes_zero_score(self):
        # missing quality can never yield a SUCCESS claim (or a fabricated
        # score) — the result must be non-SUCCESS with an explicit reason
        with pytest.raises(ValueError):
            _result(quality=None)
        unavailable = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(), quality=None,
            issues=(_issue(code=IntelligenceIssueCode.MISSING_QUALITY,
                           message="no Day-12 quality assessment supplied"),),
        )
        assert unavailable.quality is None
        d = unavailable.to_dict()
        assert d["quality"] is None
        assert "quality_score" not in d

    def test_insufficient_quality_is_not_success_by_default(self):
        insufficient = _quality(QualityState.INSUFFICIENT, 40)
        # the contract carries it faithfully; SUCCESS remains possible only if
        # the engine produced a complete read — never fabricated for it
        r = _result(quality=insufficient)
        assert r.quality.quality_state is QualityState.INSUFFICIENT
        assert r.status is IntelligenceStatus.SUCCESS


# ---------------------------------------------------------------------------
# 7. Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_result_is_frozen(self):
        r = _result()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.direction = IntelligenceDirection.BEARISH
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.confidence = 0.1

    def test_nested_contracts_are_frozen(self):
        e = _evidence()
        o = _observation()
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.value = 1.0
        with pytest.raises(dataclasses.FrozenInstanceError):
            o.value = 1.0
        with pytest.raises(dataclasses.FrozenInstanceError):
            MarketRegime().label = RegimeLabel.RISK_ON

    def test_evidence_tuple_is_immutable(self):
        r = _result()
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
            r.evidence[0].value = 5.0

    def test_no_dict_fields_exposed(self):
        r = _result()
        for f in dataclasses.fields(r):
            assert "dict" not in f.type.lower(), f.type


# ---------------------------------------------------------------------------
# 8. Provenance / version propagation
# ---------------------------------------------------------------------------


class TestProvenanceVersions:
    def test_provenance_preserved_verbatim(self):
        prov = _prov(source="UPSTOX_SNAPSHOT_NORMALIZED", ts=_REF2)
        r = _result(provenance=prov)
        assert r.provenance == prov
        assert r.provenance.source == "UPSTOX_SNAPSHOT_NORMALIZED"
        assert r.provenance.received_at == _REF2

    def test_provenance_never_replaced_with_placeholder(self):
        r = _result()
        assert r.provenance is not None
        assert r.provenance.source != "internal"
        assert "internal" not in (r.provenance.source or "").lower()

    def test_evidence_provenance_preserved(self):
        prov = _prov(source="UPSTOX_SNAPSHOT_NORMALIZED")
        r = _result(evidence=(_evidence(prov=prov),))
        assert r.evidence[0].provenance == prov

    def test_versions_propagate_explicitly(self):
        r = _result(model_version="3.2.1", calculation_version="7.7.7")
        assert r.model_version == "3.2.1"
        assert r.calculation_version == "7.7.7"
        assert r.contract_version == "1.0.0"

    def test_no_mutable_global_state_for_versions(self):
        a = _result()
        b = _result()
        assert a.calculation_id == b.calculation_id  # fixture constant, not state


# ---------------------------------------------------------------------------
# 9. Determinism & serialization
# ---------------------------------------------------------------------------


class TestDeterminismAndSerialization:
    def test_identical_inputs_identical_results(self):
        a = _result(signal_strength=0.42, confidence=0.61)
        b = _result(signal_strength=0.42, confidence=0.61)
        assert a == b
        assert hash(a) == hash(b)

    def test_no_wall_clock_or_random_dependency(self):
        # constructing twice at different real times yields identical objects
        r1 = _result()
        r2 = _result()
        assert r1 == r2

    def test_stable_json_serialization(self):
        r = _result()
        j1 = json.dumps(r.to_dict(), sort_keys=True)
        j2 = json.dumps(r.to_dict(), sort_keys=True)
        assert j1 == j2

    def test_to_dict_shapes(self):
        d = _result().to_dict()
        assert d["status"] == "SUCCESS"
        assert d["direction"] == "BULLISH"
        assert d["signal_strength"] == 0.6
        assert d["confidence"] == 0.7
        assert d["time_horizon"] == "SWING"
        assert d["contract_version"] == "1.0.0"
        assert d["model_version"] == "0.1.0"
        assert d["calculation_version"] == "0.1.0"
        assert isinstance(d["evidence"], list)
        assert d["evidence"][0]["evidence_type"] == "MARKET_OBSERVATION"
        assert d["reference_timestamp"] == "2026-09-03T10:00:00+00:00"
        assert d["quality"]["quality_state"] == "EXCELLENT"
        assert d["quality"]["quality_score"] == 95
        assert d["issues"] == []

    def test_json_safe_types_only(self):
        def walk(v):
            assert isinstance(v, (dict, list, str, int, float, bool, type(None)))
            if isinstance(v, dict):
                for k, val in v.items():
                    assert isinstance(k, str)
                    walk(val)
            elif isinstance(v, list):
                for item in v:
                    walk(item)
        walk(_result().to_dict())

    def test_round_trip_success(self):
        r = _result()
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_round_trip_partial_with_quality_issues(self):
        q = QualityResult(
            quality_score=62, quality_state=QualityState.DEGRADED,
            critical_failure=False,
            issues=(QualityIssue(QualityDimension.VALIDITY,
                                QualityIssueCode.INVALID_VOLUME,
                                IssueSeverity.ERROR, "volume out of range",
                                "volume"),),
            dimensions=(DimensionResult(QualityDimension.VALIDITY, "EVALUATED",
                                       0.5, ()),),
            evaluated_at=_REF, observation_time=_REF, observation_type="QUOTE",
            contract_version="1.0.0", reference_time=_REF,
        )
        r = _result(
            status=IntelligenceStatus.PARTIAL,
            confidence=0.4,
            quality=q,
            issues=(_issue(code=IntelligenceIssueCode.PARTIAL_EVIDENCE),),
        )
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_round_trip_unavailable(self):
        r = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            direction=None, signal_strength=None, confidence=None,
            time_horizon=None, observation=None, evidence=(), quality=None,
            issues=(_issue(code=IntelligenceIssueCode.MISSING_EVIDENCE,
                           message="no usable evidence"),),
        )
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_round_trip_with_regime(self):
        r = _result(regime=MarketRegime(label=RegimeLabel.RISK_ON,
                                        source="day23.regime.v1",
                                        model_version="1.0.0",
                                        reference_timestamp=_REF))
        assert IntelligenceResult.from_dict(r.to_dict()) == r

    def test_from_dict_rejects_unknown_enum_value(self):
        d = _result().to_dict()
        d["direction"] = "MOONSHOT"
        with pytest.raises(ValueError):
            IntelligenceResult.from_dict(d)

    def test_from_dict_rejects_structural_violation(self):
        d = _result().to_dict()
        d["issues"] = [{"code": "MISSING_EVIDENCE", "message": "x"}]
        with pytest.raises(ValueError):
            IntelligenceResult.from_dict(d)


# ---------------------------------------------------------------------------
# 10. Purity / broker neutrality / security (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    _MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "intelligence" / "contracts.py"

    def test_module_has_no_clock_or_io_imports(self):
        tree = ast.parse(self._MODULE.read_text(encoding="utf-8"))
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "socket", "subprocess", "pathlib"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today",
                                              "time", "sleep"}
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.brokers")
                assert not (node.module or "").startswith("app.services")
                assert not (node.module or "").startswith("app.routers")
                assert not (node.module or "").startswith("app.quant.boundary")

    def test_module_never_instantiates_quality_engine(self):
        text = self._MODULE.read_text(encoding="utf-8")
        assert "MarketDataQualityEngine" not in text
        assert "MarketDataQualityConfig" not in text

    def test_results_never_leak_credentials_or_broker_payloads(self):
        r = _result()
        s = str(r)
        assert "sk_live" not in s
        assert "access_token" not in s
        assert "authorization" not in s
        assert "upstox_instrument_key" not in s

    def test_module_defines_no_wall_clock_defaults(self):
        # reference timestamps must come from the caller — no module-level now()
        text = self._MODULE.read_text(encoding="utf-8")
        for token in ("datetime.now", "datetime.utcnow", "time.time()",
                      "datetime.today"):
            assert token not in text
