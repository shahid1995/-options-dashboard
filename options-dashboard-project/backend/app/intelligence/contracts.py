"""Day 19 — Deterministic Intelligence Contract Foundation.

The canonical, broker-neutral interface between the Quantitative Core
(Days 14-18) and every future Intelligence Engine (Days 20-26+)::

    Market Data -> Data Quality -> Quantitative Core
        -> Intelligence Contract (this module)
        -> Intelligence Engines (future days)

This module defines the contract ONLY — no intelligence engine, no regime
detection, no synthesis, no opportunity/strategy consumers.

Design rules
------------
1. **Three separate concepts, never collapsed**:
   * ``signal_strength`` — how strong the observed/derived signal is (0..1);
   * ``confidence`` — how confident the engine is that its interpretation is
     valid (0..1);
   * ``quality`` — the preserved Day-12 :class:`QualityResult` envelope
     (score + state + structured issues), never recomputed and never treated
     as strength or confidence.
2. **No fabrication.**  Missing evidence/values stay missing.  ``SUCCESS``
   requires complete evidence with finite values, an observation, direction,
   strength, confidence, horizon, provenance, a genuinely aware reference
   timestamp, the preserved Day-12 :class:`QualityResult` and zero issues.
   A ``None``-valued evidence entry can never underpin ``SUCCESS``; missing
   data — including a missing quality assessment — is never coerced to zero,
   NEUTRAL or EXCELLENT and never becomes success.
3. **Status/issue consistency.**  ``PARTIAL`` requires evidence + issues;
   ``UNAVAILABLE``/``INVALID`` forbid interpretation fields and require
   structured issues that preserve the reason.
4. **Directional vocabulary.**  ``BULLISH/BEARISH/NEUTRAL/MIXED/UNKNOWN`` are
   distinct — MIXED and UNKNOWN are never collapsed into NEUTRAL.  A
   directional claim (BULLISH/BEARISH/MIXED) requires positive strength AND
   positive confidence (a structural rule — no market-domain inference).
5. **Deterministic & immutable.**  All contracts are frozen dataclasses with
   no dict fields.  Every timestamp is supplied explicitly (tz-aware); the
   module never reads the wall clock, random state, network, filesystem,
   database or broker state.
6. **Broker-neutral.**  This package imports only ``app.market_data``
   (canonical, broker-free) and the Day-14 quant contract types; zero broker
   modules, zero broker payload field names, zero credentials.
7. **Versioning.**  ``INTELLIGENCE_CONTRACT_VERSION`` is an explicit module
   constant; model/calculation versions are supplied by the producing engine
   and preserved verbatim — never invented, never stored in mutable global
   state.
8. **Serialization.**  ``to_dict()`` produces a deterministic JSON-safe dict
   (enums -> value, datetimes -> ISO-8601, tuples -> lists, ``None`` kept);
   ``from_dict()`` rebuilds the frozen contract and re-runs every structural
   validation.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from app.market_data.contracts import Provenance, QualityState
from app.market_data.quality import (
    DimensionResult,
    IssueSeverity,
    QualityDimension,
    QualityIssue,
    QualityIssueCode,
    QualityResult,
)

#: Explicit contract version — bumped only on backward-incompatible change.
INTELLIGENCE_CONTRACT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Vocabulary (explicit, broker-neutral enums)
# ---------------------------------------------------------------------------


class IntelligenceStatus(str, Enum):
    """Outcome of an intelligence evaluation.

    ``PARTIAL`` means an interpretation was produced from incomplete evidence
    (structured issues state what is missing); ``UNAVAILABLE`` means no
    interpretation could be produced at all; ``INVALID`` means the evaluation
    was attempted on structurally invalid input.  Missing data never becomes
    SUCCESS.
    """

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class IntelligenceDirection(str, Enum):
    """Canonical directional semantics.

    ``MIXED`` (conflicting evidence on both sides) and ``UNKNOWN`` (no
    reliable direction could be determined) are distinct states — neither is
    collapsed into ``NEUTRAL``.
    """

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class TimeHorizon(str, Enum):
    """Explicit intelligence evaluation horizon."""

    INTRADAY = "INTRADAY"
    SHORT_TERM = "SHORT_TERM"
    SWING = "SWING"
    EXPIRY = "EXPIRY"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    """Kind of supporting evidence an engine may cite.

    Engine-specific evidence kinds (e.g. a positioning delta) are additive
    enum extensions later; CE/PE/underlying identity is carried by the
    canonical instrument reference in ``source_reference_id``, never encoded
    in the evidence type.
    """

    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    QUANT_DERIVED = "QUANT_DERIVED"
    QUALITY_ASSESSMENT = "QUALITY_ASSESSMENT"


class RegimeLabel(str, Enum):
    """Structural market-regime vocabulary for attachment only.

    Day 19 defines the type; Day 23 owns actual regime detection and may
    extend this enum additively.
    """

    UNKNOWN = "UNKNOWN"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class IntelligenceIssueCode(str, Enum):
    """Structured, machine-readable intelligence issue categories.

    Day-12 quality issue codes remain the quality engine's taxonomy and travel
    inside the preserved :class:`QualityResult`; these codes are the
    intelligence envelope's own.
    """

    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    MISSING_QUALITY = "MISSING_QUALITY"
    INSUFFICIENT_QUALITY = "INSUFFICIENT_QUALITY"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    MISSING_DIRECTION = "MISSING_DIRECTION"
    MISSING_CONFIDENCE = "MISSING_CONFIDENCE"
    MISSING_SIGNAL_STRENGTH = "MISSING_SIGNAL_STRENGTH"
    MISSING_HORIZON = "MISSING_HORIZON"
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"
    CONFLICTING_DIRECTION = "CONFLICTING_DIRECTION"
    INVALID_INPUT_VALUE = "INVALID_INPUT_VALUE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Value helpers (deterministic — never wall-clock / random / IO)
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_finite_or_none(value: float | None, name: str) -> None:
    if value is not None and (
        not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number or None")


def _require_range_or_none(value: float | None, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0]")


def _require_aware_or_none(ts: datetime | None, name: str) -> None:
    if ts is not None and not _is_aware(ts):
        raise ValueError(f"{name} must be genuinely timezone-aware when present")


def _is_aware(ts: datetime | None) -> bool:
    """Genuine Python datetime awareness: tzinfo exists AND its ``utcoffset``
    is not ``None`` (a tzinfo whose ``utcoffset()`` returns None is naive in
    effect and must not pass as aware).  Deterministic — never reads the wall
    clock and never synthesizes an offset."""
    if ts is None or ts.tzinfo is None:
        return False
    return ts.tzinfo.utcoffset(ts) is not None


# ---------------------------------------------------------------------------
# Evidence / observation / regime / issue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntelligenceEvidence:
    """One piece of evidence supporting an intelligence result.

    * ``source_reference_id`` — canonical reference to the underlying
      observation/calculation that produced this evidence (required).
    * ``evidence_type`` — :class:`EvidenceType` kind.
    * ``value`` — observed/derived value; ``None`` means genuinely missing
      (never coerced to zero).
    * ``provenance`` — Day-9 :class:`Provenance` of the evidence, preserved
      verbatim when supplied.
    * Versions are explicit per-evidence where the source has them.
    """

    source_reference_id: str
    evidence_type: EvidenceType
    value: float | None = None
    unit: str | None = None
    reference_timestamp: datetime | None = None
    provenance: Provenance | None = None
    model_version: str | None = None
    calculation_version: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_reference_id, "source_reference_id")
        if not isinstance(self.evidence_type, EvidenceType):
            raise ValueError("evidence_type must be an EvidenceType")
        _require_finite_or_none(self.value, "value")
        if self.unit is not None:
            _require_text(self.unit, "unit")
        _require_aware_or_none(self.reference_timestamp, "reference_timestamp")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")
        for name in ("model_version", "calculation_version"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)


@dataclass(frozen=True)
class IntelligenceObservation:
    """The measured/derived metric an intelligence result is about.

    ``value`` is required and finite — an observation is never fabricated; an
    engine with nothing measured produces no observation (and therefore never
    a SUCCESS claim).
    """

    metric_name: str
    value: float
    unit: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.metric_name, "metric_name")
        if not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
            raise ValueError("value must be a finite number")
        if self.unit is not None:
            _require_text(self.unit, "unit")


@dataclass(frozen=True)
class MarketRegime:
    """Regime attachment — a type only (Day 19); detection is Day 23's scope."""

    label: RegimeLabel = RegimeLabel.UNKNOWN
    source: str | None = None
    model_version: str | None = None
    reference_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, RegimeLabel):
            raise ValueError("label must be a RegimeLabel")
        for name in ("source", "model_version"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        _require_aware_or_none(self.reference_timestamp, "reference_timestamp")


@dataclass(frozen=True)
class IntelligenceIssue:
    """A structured, machine-readable intelligence issue.

    ``message`` is a safe static string — never a broker payload, credential
    or exception text.
    """

    code: IntelligenceIssueCode
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, IntelligenceIssueCode):
            raise ValueError("code must be an IntelligenceIssueCode")
        _require_text(self.message, "message")
        if self.field is not None:
            _require_text(self.field, "field")


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------

_DIRECTIONAL_CLAIMS = (
    IntelligenceDirection.BULLISH,
    IntelligenceDirection.BEARISH,
    IntelligenceDirection.MIXED,
)


@dataclass(frozen=True)
class IntelligenceResult:
    """Canonical deterministic intelligence result.

    Keeps signal strength, confidence and data quality separate; preserves
    Day-9 provenance and Day-12 quality whole; exposes explicit status and
    structured issues.  Cross-field structural rules are enforced at
    construction (see the module docstring) — engines never produce a
    ``SUCCESS`` from missing evidence or coerce missing values.
    """

    calculation_id: str
    status: IntelligenceStatus
    direction: IntelligenceDirection | None = None
    signal_strength: float | None = None
    confidence: float | None = None
    time_horizon: TimeHorizon | None = None
    observation: IntelligenceObservation | None = None
    evidence: tuple[IntelligenceEvidence, ...] = ()
    regime: MarketRegime | None = None
    quality: QualityResult | None = None
    provenance: Provenance | None = None
    reference_timestamp: datetime | None = None
    contract_version: str = INTELLIGENCE_CONTRACT_VERSION
    model_version: str | None = None
    calculation_version: str | None = None
    issues: tuple[IntelligenceIssue, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.calculation_id, "calculation_id")
        if not isinstance(self.status, IntelligenceStatus):
            raise ValueError("status must be an IntelligenceStatus")
        if self.direction is not None and not isinstance(self.direction, IntelligenceDirection):
            raise ValueError("direction must be an IntelligenceDirection or None")
        _require_range_or_none(self.signal_strength, "signal_strength")
        _require_range_or_none(self.confidence, "confidence")
        if self.time_horizon is not None and not isinstance(self.time_horizon, TimeHorizon):
            raise ValueError("time_horizon must be a TimeHorizon or None")
        if self.observation is not None and not isinstance(self.observation, IntelligenceObservation):
            raise ValueError("observation must be an IntelligenceObservation or None")
        for item in self.evidence:
            if not isinstance(item, IntelligenceEvidence):
                raise ValueError("evidence must contain only IntelligenceEvidence entries")
        if self.regime is not None and not isinstance(self.regime, MarketRegime):
            raise ValueError("regime must be a MarketRegime or None")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")
        _require_aware_or_none(self.reference_timestamp, "reference_timestamp")
        _require_text(self.contract_version, "contract_version")
        for name in ("model_version", "calculation_version"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        for item in self.issues:
            if not isinstance(item, IntelligenceIssue):
                raise ValueError("issues must contain only IntelligenceIssue entries")

        self._validate_status_rules()

    def _validate_status_rules(self) -> None:
        status = self.status
        if status is IntelligenceStatus.SUCCESS:
            if self.observation is None:
                raise ValueError("SUCCESS requires an observation")
            if not self.evidence:
                raise ValueError("SUCCESS requires at least one evidence entry")
            if any(e.value is None for e in self.evidence):
                raise ValueError(
                    "SUCCESS cannot rest on missing (None-valued) evidence — "
                    "missing data never becomes success"
                )
            if self.direction is None:
                raise ValueError("SUCCESS requires a direction")
            if self.signal_strength is None:
                raise ValueError("SUCCESS requires a signal_strength")
            if self.confidence is None:
                raise ValueError("SUCCESS requires a confidence")
            if self.time_horizon is None:
                raise ValueError("SUCCESS requires a time_horizon")
            if self.provenance is None:
                raise ValueError("SUCCESS requires provenance")
            if not _is_aware(self.reference_timestamp):
                raise ValueError("SUCCESS requires a genuinely aware reference_timestamp")
            if self.quality is None:
                raise ValueError(
                    "SUCCESS requires the preserved Day-12 QualityResult — "
                    "missing quality never becomes success"
                )
            if self.issues:
                raise ValueError("SUCCESS must carry no issues")
        elif status is IntelligenceStatus.PARTIAL:
            if not self.evidence:
                raise ValueError("PARTIAL requires at least one evidence entry")
            if not self.issues:
                raise ValueError("PARTIAL requires at least one structured issue")
        elif status in (IntelligenceStatus.UNAVAILABLE, IntelligenceStatus.INVALID):
            if (
                self.direction is not None
                or self.signal_strength is not None
                or self.confidence is not None
                or self.time_horizon is not None
                or self.observation is not None
                or self.evidence
            ):
                raise ValueError(
                    f"{status.value} results must carry no interpretation "
                    "fields or evidence"
                )
            if not self.issues:
                raise ValueError(f"{status.value} requires at least one structured issue")
        else:  # pragma: no cover — instance check already passed
            raise ValueError(f"unknown status {status!r}")

        # Directional claims require positive strength AND positive confidence.
        if self.direction in _DIRECTIONAL_CLAIMS:
            if self.signal_strength is None or self.signal_strength <= 0.0:
                raise ValueError(
                    f"direction {self.direction.value} requires positive signal_strength"
                )
            if self.confidence is None or self.confidence <= 0.0:
                raise ValueError(
                    f"direction {self.direction.value} requires positive confidence"
                )

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """Deterministic, JSON-safe representation (see module docstring)."""
        return {
            "calculation_id": self.calculation_id,
            "status": self.status.value,
            "direction": self.direction.value if self.direction is not None else None,
            "signal_strength": self.signal_strength,
            "confidence": self.confidence,
            "time_horizon": self.time_horizon.value if self.time_horizon is not None else None,
            "observation": _fmt(self.observation),
            "evidence": [_fmt(e) for e in self.evidence],
            "regime": _fmt(self.regime),
            "quality": _fmt(self.quality),
            "provenance": _fmt(self.provenance),
            "reference_timestamp": _fmt(self.reference_timestamp),
            "contract_version": self.contract_version,
            "model_version": self.model_version,
            "calculation_version": self.calculation_version,
            "issues": [_fmt(i) for i in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IntelligenceResult":
        """Rebuild a frozen contract from a :meth:`to_dict` representation.

        Re-runs every structural validation at construction — a dict that
        violates the status rules or carries unknown enum values raises
        ``ValueError`` exactly like direct construction would.
        """
        if not isinstance(data, dict):
            raise ValueError("from_dict requires a dict")
        return cls(
            calculation_id=data["calculation_id"],
            status=IntelligenceStatus(data["status"]),
            direction=_enum_or_none(IntelligenceDirection, data.get("direction")),
            signal_strength=data.get("signal_strength"),
            confidence=data.get("confidence"),
            time_horizon=_enum_or_none(TimeHorizon, data.get("time_horizon")),
            observation=_from_dict(IntelligenceObservation, data["observation"])
            if data.get("observation") is not None
            else None,
            evidence=tuple(
                _from_dict(IntelligenceEvidence, entry) for entry in data.get("evidence", [])
            ),
            regime=_from_dict(MarketRegime, data["regime"])
            if data.get("regime") is not None
            else None,
            quality=_quality_from_dict(data.get("quality")),
            provenance=_provenance_from_dict(data.get("provenance")),
            reference_timestamp=_fromiso(data.get("reference_timestamp")),
            contract_version=data["contract_version"],
            model_version=data.get("model_version"),
            calculation_version=data.get("calculation_version"),
            issues=tuple(
                _from_dict(IntelligenceIssue, item) for item in data.get("issues", [])
            ),
        )


# ---------------------------------------------------------------------------
# Serialization helpers (generic, deterministic)
# ---------------------------------------------------------------------------


def _fmt(value) -> object:
    """Convert enums/datetimes/dataclasses/tuples into JSON-safe scalars."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if not _is_aware(value):  # defensive: naive timestamps never serialize
            raise ValueError("cannot serialize a non-genuinely-aware datetime")
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return {f.name: _fmt(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, tuple):
        return [_fmt(item) for item in value]
    return value


def _fromiso(value):
    return datetime.fromisoformat(value) if value is not None else None


def _enum_or_none(enum_cls, value):
    return enum_cls(value) if value is not None else None


def _from_dict(cls, data: dict):
    """Generic rebuild of a frozen dataclass from a ``_fmt``-produced dict.

    Field annotations drive rehydration (datetimes, enums, nested frozen
    dataclasses, tuples) and every constructor re-validates.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} payload must be a dict")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    hints = get_type_hints(cls)
    kwargs = {}
    for name, hint in hints.items():
        f = fields[name]
        has_default = f.default is not dataclasses.MISSING or (
            f.default_factory is not dataclasses.MISSING
        )
        if not has_default and name not in data:
            raise ValueError(f"{cls.__name__} payload is missing required field {name!r}")
        kwargs[name] = _rehydrate(hint, data.get(name))
    return cls(**kwargs)


def _rehydrate(hint, raw):
    if raw is None:
        return None
    origin = get_origin(hint)
    if origin in (tuple, list):
        (inner,) = get_args(hint)
        return tuple(_rehydrate(inner, item) for item in raw)
    if origin is Union or origin is UnionType:
        candidates = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(candidates) == 1:
            return _rehydrate(candidates[0], raw)
        raise ValueError(f"ambiguous union annotation {hint!r}")
    if isinstance(raw, dict):
        return _from_dict(hint, raw)
    if isinstance(hint, type):
        if issubclass(hint, Enum):
            return hint(raw)
        if issubclass(hint, datetime):
            return datetime.fromisoformat(raw)
        if hint is bool and not isinstance(raw, bool):
            raise ValueError("expected a boolean")
    return raw


def _quality_from_dict(data) -> QualityResult | None:
    """Rehydrate the Day-12 quality envelope (explicit field mapping)."""
    if data is None:
        return None
    return QualityResult(
        quality_score=data["quality_score"],
        quality_state=QualityState(data["quality_state"]),
        critical_failure=data["critical_failure"],
        issues=tuple(
            QualityIssue(
                dimension=QualityDimension(issue["dimension"]),
                code=QualityIssueCode(issue["code"]),
                severity=IssueSeverity(issue["severity"]),
                message=issue["message"],
                field=issue.get("field"),
            )
            for issue in data.get("issues", [])
        ),
        dimensions=tuple(
            DimensionResult(
                dimension=QualityDimension(dim["dimension"]),
                status=dim["status"],
                score=dim["score"],
                issues=tuple(
                    QualityIssue(
                        dimension=QualityDimension(issue["dimension"]),
                        code=QualityIssueCode(issue["code"]),
                        severity=IssueSeverity(issue["severity"]),
                        message=issue["message"],
                        field=issue.get("field"),
                    )
                    for issue in dim.get("issues", [])
                ),
            )
            for dim in data.get("dimensions", [])
        ),
        evaluated_at=_fromiso(data.get("evaluated_at")),
        observation_time=_fromiso(data.get("observation_time")),
        observation_type=data["observation_type"],
        contract_version=data.get("contract_version"),
        reference_time=_fromiso(data.get("reference_time")),
    )


def _provenance_from_dict(data) -> Provenance | None:
    if data is None:
        return None
    return Provenance(
        source=data["source"],
        collection_mode=data["collection_mode"],
        received_at=datetime.fromisoformat(data["received_at"]),
        normalization_version=data["normalization_version"],
        contract_version=data["contract_version"],
        transformation_id=data.get("transformation_id"),
    )
