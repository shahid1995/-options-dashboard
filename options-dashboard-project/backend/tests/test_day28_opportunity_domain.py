"""Day 28 — Opportunity Domain tests (RED-phase contract).

Proves the deterministic Observation -> Signal -> Setup -> Opportunity
pipeline on the approved Days 19-26 Intelligence foundation:

    upstream IntelligenceResult (Days 20-26 output)
        -> Observation (typed envelope, upstream is the single source)
        -> Signal (directional or non-directional interpretation)
        -> Setup (directional trading-setup frame; quality/horizon/regime)
        -> Opportunity (explainable discovery object, CANDIDATE status)
    STOP at Opportunity -- never an order, never an execution intent.

Rules locked by these tests
---------------------------
1. The upstream Day-19 `IntelligenceResult` object is the single source of
   truth at every stage (`is`-identity through the whole pipeline).  No
   duplicated field can drift; no second market-data system exists.
2. A Signal requires an interpretable SUCCESS upstream observation
   (missing quality / PARTIAL / UNAVAILABLE observations cannot become
   Signals).  Non-directional Signals (NEUTRAL / UNKNOWN / MIXED) are valid
   Signals but can NEVER form a directional Setup.
3. Setups and Opportunities require: directional upstream read, SUCCESS
   status, present-and-usable quality (state != INSUFFICIENT; DEGRADED is
   usable and visible), and a present horizon -- the domain NEVER invents
   EXPIRY or any horizon.
4. The authoritative Day-23 MarketRegime is preserved verbatim (identity);
   RANGING / UNKNOWN / volatility-only labels never become direction.
5. strength != confidence != quality, preserved from upstream verbatim.
6. Expected behavior uses CANDIDATE language only; the pipeline produces
   DIRECTIONAL_CONTINUATION_CANDIDATE today (other values are reserved
   vocabulary for upstream evidence these inputs do not carry).  No
   probabilities/returns/targets are invented.
7. Invalidation conditions are non-empty, deterministic, state/evidence
   based, and describe the thesis boundary -- never stop-losses,
   cancellations, position management or broker actions.
8. Identity is caller-supplied and deterministic; no UUID/random/wall-clock.
9. Opportunity creation contains ZERO broker/execution behavior: no order
   creation/submission/modification/cancellation, no broker imports, no
   network/DB/filesystem I/O (AST-guarded).
10. Deterministic: identical inputs => identical stage objects.
11. Serialization (JSON-safe to_dict/from_dict) round-trips every stage
    without losing upstream evidence/quality/regime/provenance/timestamps.
12. Golden expectations are explicit and independent (see examples below).

Golden examples
---------------
SUCCESS BULLISH synthesis result (strength 0.5, confidence 0.75, horizon
EXPIRY, EXCELLENT quality, TRENDING regime) =>
  to_signal -> Signal BULLISH 0.5/0.75, horizon EXPIRY, regime TRENDING
  to_setup  -> Setup BULLISH, DIRECTIONAL_CONTINUATION_CANDIDATE, 3
               invalidation conditions, same projections
  to_opportunity -> Opportunity CANDIDATE, thesis contains "BULLISH",
               "NIFTY", "DIRECTIONAL_CONTINUATION_CANDIDATE"
SUCCESS MIXED / UNKNOWN / NEUTRAL results => Signal only; to_setup raises.
SUCCESS with INSUFFICIENT quality => Signal only; to_setup raises.
PARTIAL / UNAVAILABLE observations => to_signal raises.
"""

from __future__ import annotations

import ast
import json
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
    IntelligenceIssue,
    IntelligenceIssueCode,
    IntelligenceObservation,
    IntelligenceResult,
    IntelligenceStatus,
    MarketRegime,
    RegimeLabel,
    TimeHorizon,
)
from app.opportunity.contracts import (
    ExpectedBehavior,
    Observation,
    ObservationKind,
    Opportunity,
    OpportunityStatus,
    Setup,
    Signal,
)
from app.opportunity.pipeline import (
    discover_opportunity,
    to_opportunity,
    to_setup,
    to_signal,
)

_REF = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
_UNSET = object()
NIFTY = "NIFTY"
SYNTH = "intelligence.synthesis.v1"


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


def _regime(label: RegimeLabel = RegimeLabel.TRENDING) -> MarketRegime:
    return MarketRegime(label=label, source="intelligence.regime.v1",
                        model_version="1.0.0", reference_timestamp=_REF)


def _evidence(value: float = 0.5, key: str = "bull:test") -> IntelligenceEvidence:
    return IntelligenceEvidence(
        source_reference_id=f"synthesis:{NIFTY}:2026-09-24:{key}",
        evidence_type=EvidenceType.QUANT_DERIVED,
        value=value,
        unit="score_0_1",
        reference_timestamp=_REF,
        provenance=_prov(),
        model_version="1.0.0",
        calculation_version="1.0.0",
    )


def _result(*, direction: IntelligenceDirection | None = IntelligenceDirection.BULLISH,
            status: IntelligenceStatus = IntelligenceStatus.SUCCESS,
            strength: float | None = 0.5,
            confidence: float | None = 0.75,
            horizon: TimeHorizon | None = TimeHorizon.EXPIRY,
            quality=_UNSET, regime=None, calc_id: str = SYNTH,
            issue_codes: tuple[IntelligenceIssueCode, ...] = ()) \
        -> IntelligenceResult:
    q = quality if quality is not _UNSET else _quality()
    issues = tuple(
        IntelligenceIssue(code=c, message=c.value) for c in issue_codes
    ) if issue_codes else ()
    if status is IntelligenceStatus.SUCCESS:
        return IntelligenceResult(
            calculation_id=calc_id,
            status=status,
            direction=direction,
            signal_strength=strength,
            confidence=confidence,
            time_horizon=horizon,
            observation=IntelligenceObservation(
                metric_name="synthesis_strength",
                value=float(strength or 0.0), unit="score_0_1"),
            evidence=(_evidence(),),
            regime=regime,
            quality=q,
            provenance=_prov(),
            reference_timestamp=_REF,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version="1.0.0",
            calculation_version="1.0.0",
            issues=issues,
        )
    if status is IntelligenceStatus.PARTIAL:
        # PARTIAL requires >=1 evidence row + >=1 structured issue
        return IntelligenceResult(
            calculation_id=calc_id,
            status=status,
            direction=direction,
            signal_strength=strength,
            confidence=confidence,
            time_horizon=horizon,
            observation=None,
            evidence=(_evidence(),),
            regime=regime,
            quality=q,
            provenance=_prov(),
            reference_timestamp=_REF,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version="1.0.0",
            calculation_version="1.0.0",
            issues=issues,
        )
    # UNAVAILABLE / INVALID: no interpretation fields, no evidence, issues
    return IntelligenceResult(
        calculation_id=calc_id,
        status=status,
        direction=None,
        signal_strength=None,
        confidence=None,
        time_horizon=None,
        observation=None,
        evidence=(),
        regime=regime,
        quality=q,
        provenance=_prov(),
        reference_timestamp=_REF,
        contract_version=INTELLIGENCE_CONTRACT_VERSION,
        model_version="1.0.0",
        calculation_version="1.0.0",
        issues=issues,
    )


def _obs(result: IntelligenceResult, obs_id: str = "obs-1") -> Observation:
    return Observation(observation_id=obs_id, underlying=NIFTY,
                       expiry="2026-09-24", upstream=result)


# ---------------------------------------------------------------------------
# 1. Observation contract
# ---------------------------------------------------------------------------


class TestObservation:
    def test_valid_observation(self):
        result = _result()
        obs = _obs(result)
        assert obs.observation_id == "obs-1"
        assert obs.underlying == NIFTY
        assert obs.expiry == "2026-09-24"
        assert obs.kind is ObservationKind.INTELLIGENCE_RESULT

    def test_projections_read_upstream(self):
        result = _result()
        obs = _obs(result)
        assert obs.upstream is result
        assert obs.status is IntelligenceStatus.SUCCESS
        assert obs.direction is IntelligenceDirection.BULLISH
        assert obs.signal_strength == pytest.approx(0.5)
        assert obs.confidence == pytest.approx(0.75)
        assert obs.time_horizon is TimeHorizon.EXPIRY
        assert obs.quality is result.quality
        assert obs.provenance is result.provenance
        assert obs.reference_timestamp == _REF
        assert obs.evidence == result.evidence

    def test_missing_observation_id_rejected(self):
        with pytest.raises(ValueError):
            Observation(observation_id="", underlying=NIFTY, upstream=_result())

    def test_missing_underlying_rejected(self):
        with pytest.raises(ValueError):
            Observation(observation_id="obs-1", underlying="", upstream=_result())

    def test_upstream_type_checked(self):
        with pytest.raises(ValueError):
            Observation(observation_id="obs-1", underlying=NIFTY,
                        upstream="not-a-result")

    def test_kind_type_checked(self):
        with pytest.raises(ValueError):
            Observation(observation_id="obs-1", underlying=NIFTY,
                        upstream=_result(), kind="INTELLIGENCE_RESULT")

    def test_partial_upstream_is_a_valid_observation(self):
        # observing an incomplete upstream is legitimate; the SIGNAL gate
        # blocks it later -- observations record facts
        partial = _result(status=IntelligenceStatus.PARTIAL, direction=None,
                          issue_codes=(IntelligenceIssueCode.MISSING_QUALITY,))
        obs = _obs(partial)
        assert obs.status is IntelligenceStatus.PARTIAL
        assert obs.direction is None

    def test_serialization_round_trip(self):
        obs = _obs(_result(regime=_regime()))
        rebuilt = Observation.from_dict(obs.to_dict())
        assert rebuilt.to_dict() == obs.to_dict()
        assert rebuilt.upstream is not obs.upstream  # rebuilt, not shared

    def test_serialization_is_json_safe(self):
        json.dumps(_obs(_result(regime=_regime())).to_dict())


# ---------------------------------------------------------------------------
# 2. Signal contract + pipeline gate
# ---------------------------------------------------------------------------


class TestSignal:
    def test_bullish_signal(self):
        result = _result()
        s = to_signal(_obs(result), "sig-1")
        assert s.signal_id == "sig-1"
        assert s.observation_id == "obs-1"
        assert s.upstream is result
        assert s.direction is IntelligenceDirection.BULLISH
        assert s.signal_strength == pytest.approx(0.5)
        assert s.confidence == pytest.approx(0.75)
        assert s.time_horizon is TimeHorizon.EXPIRY
        assert s.explanation

    def test_bearish_signal(self):
        s = to_signal(_obs(_result(direction=IntelligenceDirection.BEARISH)), "sig-1")
        assert s.direction is IntelligenceDirection.BEARISH

    def test_neutral_signal_is_valid_but_non_directional(self):
        s = to_signal(
            _obs(_result(direction=IntelligenceDirection.NEUTRAL, strength=0.0)),
            "sig-1")
        assert s.status is IntelligenceStatus.SUCCESS
        assert s.direction is IntelligenceDirection.NEUTRAL

    def test_unknown_signal_is_valid_but_non_directional(self):
        s = to_signal(
            _obs(_result(direction=IntelligenceDirection.UNKNOWN, strength=0.0)),
            "sig-1")
        assert s.direction is IntelligenceDirection.UNKNOWN

    def test_mixed_signal_is_valid_but_non_directional(self):
        s = to_signal(
            _obs(_result(direction=IntelligenceDirection.MIXED)), "sig-1")
        assert s.direction is IntelligenceDirection.MIXED

    def test_partial_observation_cannot_become_signal(self):
        partial = _result(status=IntelligenceStatus.PARTIAL, direction=None,
                          issue_codes=(IntelligenceIssueCode.MISSING_QUALITY,))
        with pytest.raises(ValueError) as exc:
            to_signal(_obs(partial), "sig-1")
        assert "SUCCESS" in str(exc.value)

    def test_unavailable_observation_cannot_become_signal(self):
        unavailable = _result(
            status=IntelligenceStatus.UNAVAILABLE, direction=None,
            issue_codes=(IntelligenceIssueCode.MISSING_EVIDENCE,))
        with pytest.raises(ValueError):
            to_signal(_obs(unavailable), "sig-1")

    def test_quality_preserved_identity(self):
        result = _result()
        s = to_signal(_obs(result), "sig-1")
        assert s.quality is result.quality

    def test_regime_preserved_identity(self):
        regime = _regime()
        s = to_signal(_obs(_result(regime=regime)), "sig-1")
        assert s.regime is regime

    def test_evidence_preserved(self):
        result = _result()
        s = to_signal(_obs(result), "sig-1")
        assert s.evidence == result.evidence
        assert len(s.evidence) >= 1

    def test_strength_confidence_quality_separate(self):
        s = to_signal(_obs(_result()), "sig-1")
        assert s.signal_strength != s.confidence
        assert s.confidence != s.quality.quality_score

    def test_explanation_deterministic(self):
        s1 = to_signal(_obs(_result()), "sig-1")
        s2 = to_signal(_obs(_result()), "sig-1")
        assert s1.explanation == s2.explanation
        assert SYNTH in s1.explanation

    def test_explanation_required_non_blank(self):
        with pytest.raises(ValueError):
            Signal(signal_id="sig-1", observation_id="obs-1", underlying=NIFTY,
                   upstream=_result(), explanation="   ")

    def test_direct_signal_validation(self):
        with pytest.raises(ValueError):
            Signal(signal_id="sig-1", observation_id="obs-1", underlying=NIFTY,
                   upstream="nonsense", explanation="x")

    def test_serialization_round_trip(self):
        s = to_signal(_obs(_result(regime=_regime())), "sig-1")
        rebuilt = Signal.from_dict(s.to_dict())
        assert rebuilt.to_dict() == s.to_dict()
        assert rebuilt.direction is IntelligenceDirection.BULLISH

    def test_deterministic_repeat(self):
        s = to_signal(_obs(_result()), "sig-1")
        assert to_signal(_obs(_result()), "sig-1").to_dict() == s.to_dict()


# ---------------------------------------------------------------------------
# 3. Setup contract + gates
# ---------------------------------------------------------------------------


class TestSetup:
    def test_valid_bullish_setup(self):
        s = to_signal(_obs(_result()), "sig-1")
        setup = to_setup(s, "setup-1")
        assert setup.setup_id == "setup-1"
        assert setup.signal_id == "sig-1"
        assert setup.direction is IntelligenceDirection.BULLISH
        assert setup.expected_behavior is ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE
        assert setup.time_horizon is TimeHorizon.EXPIRY
        assert len(setup.invalidation_conditions) >= 1

    def test_valid_bearish_setup(self):
        s = to_signal(_obs(_result(direction=IntelligenceDirection.BEARISH)), "sig-1")
        setup = to_setup(s, "setup-1")
        assert setup.direction is IntelligenceDirection.BEARISH
        assert setup.expected_behavior is ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE

    def test_non_directional_signal_cannot_form_setup(self):
        for direction, strength in ((IntelligenceDirection.NEUTRAL, 0.0),
                                    (IntelligenceDirection.UNKNOWN, 0.0),
                                    (IntelligenceDirection.MIXED, 0.5)):
            s = to_signal(_obs(_result(direction=direction, strength=strength)),
                          "sig-1")
            with pytest.raises(ValueError) as exc:
                to_setup(s, "setup-1")
            assert "directional" in str(exc.value)

    def test_insufficient_quality_cannot_form_setup(self):
        result = _result(quality=_quality(QualityState.INSUFFICIENT))
        s = to_signal(_obs(result), "sig-1")
        with pytest.raises(ValueError) as exc:
            to_setup(s, "setup-1")
        assert "quality" in str(exc.value).lower()

    def test_degraded_quality_is_usable_and_visible(self):
        result = _result(quality=_quality(QualityState.DEGRADED))
        s = to_signal(_obs(result), "sig-1")
        setup = to_setup(s, "setup-1")
        assert setup.quality.quality_state is QualityState.DEGRADED
        assert setup.quality is result.quality

    def test_invalidation_conditions_non_empty_deterministic(self):
        s = to_signal(_obs(_result()), "sig-1")
        setup = to_setup(s, "setup-1")
        assert setup.invalidation_conditions
        assert all(c.strip() for c in setup.invalidation_conditions)
        assert to_setup(to_signal(_obs(_result()), "sig-1"),
                        "setup-1").invalidation_conditions \
            == setup.invalidation_conditions

    def test_conditions_reference_thesis_boundary_not_execution(self):
        s = to_signal(_obs(_result()), "sig-1")
        setup = to_setup(s, "setup-1")
        joined = " ".join(setup.invalidation_conditions).lower()
        for token in ("stop-loss", "stop loss", "sell", "buy", "cancel",
                      "exit order", "target price"):
            assert token not in joined

    def test_regime_propagates_identity(self):
        regime = _regime()
        s = to_signal(_obs(_result(regime=regime)), "sig-1")
        setup = to_setup(s, "setup-1")
        assert setup.regime is regime

    def test_quality_horizon_propagated(self):
        result = _result()
        setup = to_setup(to_signal(_obs(result), "sig-1"), "setup-1")
        assert setup.quality is result.quality
        assert setup.time_horizon is TimeHorizon.EXPIRY
        assert setup.evidence == result.evidence

    def test_direct_constructor_rejects_non_success_upstream(self):
        partial = _result(status=IntelligenceStatus.PARTIAL,
                          issue_codes=(IntelligenceIssueCode.MISSING_QUALITY,))
        with pytest.raises(ValueError):
            Setup(setup_id="setup-1", signal_id="sig-1", underlying=NIFTY,
                  upstream=partial,
                  expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                  invalidation_conditions=("cond",))

    def test_direct_constructor_rejects_blank_conditions(self):
        result = _result()
        with pytest.raises(ValueError):
            Setup(setup_id="setup-1", signal_id="sig-1", underlying=NIFTY,
                  upstream=result,
                  expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                  invalidation_conditions=())

    def test_direct_constructor_rejects_blank_condition_string(self):
        result = _result()
        with pytest.raises(ValueError):
            Setup(setup_id="setup-1", signal_id="sig-1", underlying=NIFTY,
                  upstream=result,
                  expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                  invalidation_conditions=("ok", "  "))

    def test_serialization_round_trip(self):
        setup = to_setup(to_signal(_obs(_result(regime=_regime())), "sig-1"),
                         "setup-1")
        rebuilt = Setup.from_dict(setup.to_dict())
        assert rebuilt.to_dict() == setup.to_dict()
        assert rebuilt.direction is IntelligenceDirection.BULLISH


# ---------------------------------------------------------------------------
# 4. Opportunity contract
# ---------------------------------------------------------------------------


class TestOpportunity:
    def _opp(self, *, direction=IntelligenceDirection.BULLISH,
             regime=None, quality=_UNSET, obs_id="obs-1", sig_id="sig-1",
             setup_id="setup-1", opp_id="opp-1") -> Opportunity:
        result = _result(direction=direction, regime=regime,
                         quality=quality if quality is not _UNSET else _quality())
        obs = _obs(result, obs_id)
        sig = to_signal(obs, sig_id)
        setup = to_setup(sig, setup_id)
        return to_opportunity(setup, opp_id)

    def test_valid_opportunity(self):
        opp = self._opp()
        assert opp.opportunity_id == "opp-1"
        assert opp.setup_id == "setup-1"
        assert opp.underlying == NIFTY
        assert opp.direction is IntelligenceDirection.BULLISH
        assert opp.status is OpportunityStatus.CANDIDATE
        assert opp.expected_behavior is ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE
        assert opp.thesis

    def test_bearish_opportunity(self):
        opp = self._opp(direction=IntelligenceDirection.BEARISH)
        assert opp.direction is IntelligenceDirection.BEARISH

    def test_non_directional_never_reaches_opportunity(self):
        for direction, strength in ((IntelligenceDirection.NEUTRAL, 0.0),
                                    (IntelligenceDirection.UNKNOWN, 0.0),
                                    (IntelligenceDirection.MIXED, 0.5)):
            result = _result(direction=direction, strength=strength)
            sig = to_signal(_obs(result), "sig-1")
            with pytest.raises(ValueError):
                to_setup(sig, "setup-1")
            with pytest.raises(ValueError):
                discover_opportunity(_obs(result), "sig-1", "setup-1", "opp-1")

    def test_thesis_explainable_and_deterministic(self):
        a = self._opp()
        b = self._opp()
        assert a.thesis == b.thesis
        assert "BULLISH" in a.thesis
        assert NIFTY in a.thesis
        assert "DIRECTIONAL_CONTINUATION_CANDIDATE" in a.thesis

    def test_regime_propagates_identity(self):
        regime = _regime()
        opp = self._opp(regime=regime)
        assert opp.regime is regime

    def test_quality_propagates_identity(self):
        q = _quality()
        opp = self._opp(quality=q)
        assert opp.quality is q

    def test_evidence_chain_reachable(self):
        opp = self._opp()
        assert opp.evidence
        assert opp.provenance is not None
        assert opp.reference_timestamp == _REF
        assert opp.time_horizon is TimeHorizon.EXPIRY

    def test_direct_constructor_rejects_unusable_quality(self):
        result = _result(quality=_quality(QualityState.INSUFFICIENT))
        with pytest.raises(ValueError):
            Opportunity(opportunity_id="opp-1", setup_id="setup-1",
                        underlying=NIFTY, upstream=result, thesis="t",
                        expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                        invalidation_conditions=("c",))

    def test_direct_constructor_rejects_blank_thesis(self):
        result = _result()
        with pytest.raises(ValueError):
            Opportunity(opportunity_id="opp-1", setup_id="setup-1",
                        underlying=NIFTY, upstream=result, thesis="  ",
                        expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                        invalidation_conditions=("c",))

    def test_status_type_checked(self):
        result = _result()
        with pytest.raises(ValueError):
            Opportunity(opportunity_id="opp-1", setup_id="setup-1",
                        underlying=NIFTY, upstream=result, thesis="t",
                        expected_behavior=ExpectedBehavior.DIRECTIONAL_CONTINUATION_CANDIDATE,
                        invalidation_conditions=("c",), status="CANDIDATE")

    def test_serialization_round_trip(self):
        opp = self._opp(regime=_regime())
        rebuilt = Opportunity.from_dict(opp.to_dict())
        assert rebuilt.to_dict() == opp.to_dict()
        assert rebuilt.direction is IntelligenceDirection.BULLISH
        assert rebuilt.regime.label is RegimeLabel.TRENDING
        assert rebuilt.quality.quality_state is QualityState.EXCELLENT

    def test_serialization_is_json_safe(self):
        json.dumps(self._opp(regime=_regime()).to_dict())

    def test_deterministic_repeat(self):
        a = self._opp()
        assert self._opp().to_dict() == a.to_dict()

    def test_strength_positive_for_directional_opportunity(self):
        assert self._opp().signal_strength == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 5. Discovery chain + adversarial
# ---------------------------------------------------------------------------


class TestDiscoveryChain:
    def test_discover_returns_opportunity(self):
        opp = discover_opportunity(_obs(_result()), "sig-1", "setup-1", "opp-1")
        assert isinstance(opp, Opportunity)
        assert opp.signal_strength == pytest.approx(0.5)

    def test_upstream_identity_preserved_across_all_stages(self):
        result = _result()
        obs = _obs(result)
        sig = to_signal(obs, "sig-1")
        setup = to_setup(sig, "setup-1")
        opp = to_opportunity(setup, "opp-1")
        assert obs.upstream is result
        assert sig.upstream is result
        assert setup.upstream is result
        assert opp.upstream is result

    def test_ids_link_through_stages(self):
        opp = discover_opportunity(_obs(_result(), "obs-x"),
                                   "sig-x", "setup-x", "opp-x")
        assert opp.setup_id == "setup-x"

    def test_missing_evidence_observation_never_manufactures_opportunity(self):
        unavailable = _result(
            status=IntelligenceStatus.UNAVAILABLE,
            issue_codes=(IntelligenceIssueCode.MISSING_EVIDENCE,))
        with pytest.raises(ValueError):
            discover_opportunity(_obs(unavailable), "sig-1", "setup-1", "opp-1")

    def test_missing_quality_never_manufactures_opportunity(self):
        partial = _result(status=IntelligenceStatus.PARTIAL,
                          issue_codes=(IntelligenceIssueCode.MISSING_QUALITY,))
        with pytest.raises(ValueError):
            discover_opportunity(_obs(partial), "sig-1", "setup-1", "opp-1")

    def test_duplicate_observations_do_not_inflate(self):
        # stateless pipeline: observing the same fact twice changes nothing
        result = _result()
        a = discover_opportunity(_obs(result, "obs-1"), "sig-1", "setup-1", "opp-1")
        b = discover_opportunity(_obs(result, "obs-2"), "sig-1", "setup-1", "opp-1")
        assert a.to_dict() == b.to_dict()

    def test_regime_without_directional_evidence_never_forms_opportunity(self):
        result = _result(direction=IntelligenceDirection.UNKNOWN, strength=0.0,
                         regime=_regime(RegimeLabel.RANGING))
        sig = to_signal(_obs(result), "sig-1")
        assert sig.regime.label is RegimeLabel.RANGING
        with pytest.raises(ValueError):
            to_setup(sig, "setup-1")

    def test_trap_type_conflicting_read_follows_same_gates(self):
        # a directional trap-candidate read (Day-25 BULL_TRAP_CANDIDATE =>
        # BEARISH) is treated exactly like any approved upstream read; no
        # special casing, no bypass, no certainty language
        result = _result(direction=IntelligenceDirection.BEARISH,
                         calc_id="intelligence.trap_detection.v1")
        sig = to_signal(_obs(result), "sig-1")
        assert sig.upstream.calculation_id == "intelligence.trap_detection.v1"
        setup = to_setup(sig, "setup-1")
        assert setup.direction is IntelligenceDirection.BEARISH
        assert "candidate" in setup.expected_behavior.value.lower()

    def test_directional_without_success_status_never_forms_opportunity(self):
        # a crafted PARTIAL result with a directional read and NO horizon
        # must fail before any EXPIRY can be invented
        partial = _result(status=IntelligenceStatus.PARTIAL,
                          direction=IntelligenceDirection.BULLISH,
                          horizon=None,
                          issue_codes=(IntelligenceIssueCode.PARTIAL_EVIDENCE,))
        with pytest.raises(ValueError) as exc:
            to_signal(_obs(partial), "sig-1")
        assert "SUCCESS" in str(exc.value)


# ---------------------------------------------------------------------------
# 6. Execution boundary + purity
# ---------------------------------------------------------------------------


class TestExecutionBoundary:
    _PKG = pathlib.Path(__file__).resolve().parents[1] / "app" / "opportunity"

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
                                   "app.streaming"):
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

    def test_opportunity_has_no_order_members(self):
        opp_fields = {f for f in vars(Opportunity)}
        for token in ("order", "execution", "position", "risk", "broker"):
            assert not any(token in f for f in opp_fields)
