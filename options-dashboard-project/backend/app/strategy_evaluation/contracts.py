"""Day 31 — Strategy-evaluation contracts (approved design).

Typed, frozen, deterministic representations for the strategy-evaluation
boundary.  Authoritative calculations are REUSED, never duplicated:

* strategy legs are the Day-18 ``OptionLeg`` pure-data leg contract;
* the deterministic calculation environment is the Day-14
  ``CalculationContext`` (explicit risk-free rate / dividend / reference
  timestamp -- the engine never reads the wall clock);
* scenario coordinates are the Day-18 ``ScenarioPoint`` type;
* scenario + Greek orchestration delegate to the Day-18
  ``evaluate_leg``/``evaluate_portfolio`` functions;
* regime channel is the Day-19 ``MarketRegime`` (label + Day-23 source);
* quality is the Day-12 ``QualityResult`` envelope, provenance is the
  Day-9 ``Provenance`` contract -- both preserved, never recomputed;
* the originating Day-28 ``Opportunity`` identity/provenance is preserved
  when supplied.

Semantics locked here
---------------------
* Every dimension has an explicit state: AVAILABLE / PARTIAL /
  UNAVAILABLE / INVALID.  Missing data is never converted to zero, to
  neutral, or to a favorable value.
* Payoff metrics are caller-supplied authoritative evidence (the payoff
  engine lives in another boundary and is NOT copied here); mixed-expiry
  valuations are explicitly flagged as approximations.
* A regime label alone never fabricates directional evidence.
* Historical behaviour exists only when real point-in-time evidence is
  supplied; no historical score is ever invented.
* Risk is informational/evaluative only -- there is no execution-verdict
  or risk-verdict vocabulary and no authorization member anywhere here.
* No single opaque suitability number is emitted: every dimension is
  inspectable (the approved design forbids arbitrary weighted scores).
  Confidence and Day-12 quality are independent caller channels.
* Identity is caller-supplied and deterministic: no UUID/random/wall-clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance, QualityState
from app.market_data.quality import QualityResult
from app.intelligence.contracts import (
    IntelligenceDirection,
    MarketRegime,
    RegimeLabel,
)
from app.opportunity.contracts import Opportunity
from app.quant.scenarios import OptionLeg, ScenarioPoint

#: Day-31 contract version (independent of the Day-19/28 contracts).
STRATEGY_EVALUATION_CONTRACT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class EvaluationContext(str, Enum):
    """Where the same evaluator is being consumed (metadata only).

    Context NEVER alters the quantitative mathematics: identical canonical
    inputs produce identical quantitative assessments in every context.
    """

    OPPORTUNITY = "OPPORTUNITY"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    RESEARCH = "RESEARCH"


class DimensionState(str, Enum):
    """State of one evaluation dimension (design §6)."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class EvaluationDimension(str, Enum):
    """The seven evaluation dimensions (fixed declaration order)."""

    PAYOFF = "PAYOFF"
    GREEKS = "GREEKS"
    SCENARIO = "SCENARIO"
    REGIME = "REGIME"
    LIQUIDITY = "LIQUIDITY"
    RISK = "RISK"
    HISTORICAL = "HISTORICAL"


class PayoffExpirySemantics(str, Enum):
    """Exactness of the supplied payoff evaluation."""

    SAME_EXPIRY_EXACT = "SAME_EXPIRY_EXACT"
    MIXED_EXPIRY_APPROXIMATE = "MIXED_EXPIRY_APPROXIMATE"


class TailClass(str, Enum):
    """Payoff tail classification (structural, not a probability)."""

    NONE = "NONE"
    UNLIMITED_GAIN = "UNLIMITED_GAIN"
    UNLIMITED_LOSS = "UNLIMITED_LOSS"


class RegimeCompatibility(str, Enum):
    """Strategy/regime directional compatibility.

    COMPATIBLE/CONFLICTED require BOTH a directional strategy read and a
    directional regime read; NON_DIRECTIONAL records that at least one of
    the two is missing -- a regime label alone never fabricates direction.
    """

    COMPATIBLE = "COMPATIBLE"
    CONFLICTED = "CONFLICTED"
    NON_DIRECTIONAL = "NON_DIRECTIONAL"


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _require_text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _is_aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _require_finite(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number or None")
    return float(value)


def _require_range(value: float | None, name: str) -> float | None:
    value = _require_finite(value, name)
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1] or None")
    return value


def _fmt_ts(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if not _is_aware(ts):
        raise ValueError("cannot serialize a non-genuinely-aware datetime")
    return ts.isoformat()


def _fmt_provenance(prov: Provenance | None) -> dict | None:
    if prov is None:
        return None
    return {
        "source": prov.source,
        "collection_mode": prov.collection_mode,
        "received_at": prov.received_at.isoformat(),
        "normalization_version": prov.normalization_version,
        "contract_version": prov.contract_version,
        "transformation_id": prov.transformation_id,
    }


def _prov_from_dict(data: dict | None) -> Provenance | None:
    if not data:
        return None
    return Provenance(
        source=data["source"],
        collection_mode=data["collection_mode"],
        received_at=datetime.fromisoformat(data["received_at"]),
        normalization_version=data["normalization_version"],
        contract_version=data["contract_version"],
        transformation_id=data.get("transformation_id"),
    )


def _leg_to_dict(leg: OptionLeg) -> dict:
    return {
        "option_type": leg.option_type.value,
        "strike": leg.strike,
        "expiry": leg.expiry,
        "quantity": leg.quantity,
        "direction": leg.direction.value,
        "entry_price": leg.entry_price,
        "implied_volatility": leg.implied_volatility,
        "quality": leg.quality.value if leg.quality else None,
        "provenance": _fmt_provenance(leg.provenance),
    }


def _leg_from_dict(data: dict) -> OptionLeg:
    return OptionLeg(
        option_type=__import__("app.market_data.contracts",
                               fromlist=["Side"]).Side(data["option_type"]),
        strike=data["strike"],
        expiry=data["expiry"],
        quantity=data["quantity"],
        direction=__import__("app.quant.scenarios",
                             fromlist=["PositionDirection"])
        .PositionDirection(data["direction"]),
        entry_price=data.get("entry_price"),
        implied_volatility=data.get("implied_volatility"),
        quality=QualityState(data["quality"]) if data.get("quality") else None,
        provenance=_prov_from_dict(data.get("provenance")),
    )


# ---------------------------------------------------------------------------
# Caller-supplied dimension evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PayoffEvidence:
    """Authoritative payoff metrics supplied by an upstream boundary.

    Day 31 does NOT reimplement the payoff engine: it consumes these
    metrics verbatim and never fabricates a payoff curve.  ``None`` fields
    stay missing; ``expiry_semantics`` marks same-expiry results exact and
    mixed-expiry results approximate.
    """

    expiry_semantics: PayoffExpirySemantics
    state: DimensionState = DimensionState.AVAILABLE
    net_debit_credit: float | None = None
    max_profit: float | None = None
    max_loss: float | None = None
    tail: TailClass = TailClass.NONE
    breakevens: tuple[float, ...] = ()
    premium_outlay: float | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.expiry_semantics, PayoffExpirySemantics):
            raise ValueError("expiry_semantics must be a PayoffExpirySemantics")
        if not isinstance(self.state, DimensionState) \
                or self.state is DimensionState.UNAVAILABLE:
            raise ValueError("payoff state must be AVAILABLE/PARTIAL/INVALID")
        for name in ("net_debit_credit", "max_profit", "max_loss",
                     "premium_outlay"):
            _require_finite(getattr(self, name), name)
        if not isinstance(self.tail, TailClass):
            raise ValueError("tail must be a TailClass")
        if not isinstance(self.breakevens, tuple) or not all(
                isinstance(b, (int, float)) and math.isfinite(b)
                for b in self.breakevens):
            raise ValueError("breakevens must be a tuple of finite numbers")
        if self.provenance is not None and \
                not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance or None")


@dataclass(frozen=True)
class LiquidityEvidence:
    """Supplied per-strategy liquidity/spread evidence."""

    state: DimensionState = DimensionState.AVAILABLE
    legs_complete: int = 0
    legs_total: int = 0
    spread_bps: float | None = None
    quality: QualityState | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState) \
                or self.state is DimensionState.UNAVAILABLE:
            raise ValueError("liquidity state must be AVAILABLE/PARTIAL/INVALID")
        if self.legs_complete < 0 or self.legs_total < 0 \
                or self.legs_complete > self.legs_total:
            raise ValueError("legs_complete must be within [0, legs_total]")
        _require_finite(self.spread_bps, "spread_bps")


@dataclass(frozen=True)
class RiskEvidence:
    """Supplied risk characteristics (evaluative input, not a verdict).

    There is deliberately no execution/risk decision vocabulary and no
    authorization field: the Day-33 central risk engine owns decisions.
    """

    state: DimensionState = DimensionState.AVAILABLE
    structural_unbounded_loss: bool | None = None
    max_loss_estimate: float | None = None
    notes: tuple[str, ...] = ()
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState) \
                or self.state is DimensionState.UNAVAILABLE:
            raise ValueError("risk state must be AVAILABLE/PARTIAL/INVALID")
        _require_finite(self.max_loss_estimate, "max_loss_estimate")
        if not isinstance(self.notes, tuple) or not all(
                isinstance(n, str) for n in self.notes):
            raise ValueError("notes must be a tuple of strings")


@dataclass(frozen=True)
class HistoricalEvidence:
    """Real point-in-time historical evidence when actually available.

    Never invented: ``observations`` counts supplied point-in-time rows and
    ``metric_note`` describes the supplied evidence -- no fabricated
    performance/historical score exists anywhere in Day 31.
    """

    state: DimensionState = DimensionState.AVAILABLE
    observations: int = 0
    metric_note: str | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DimensionState) \
                or self.state is DimensionState.UNAVAILABLE:
            raise ValueError("historical state must be AVAILABLE/PARTIAL/INVALID")
        if self.observations < 0:
            raise ValueError("observations must be non-negative")
        if self.metric_note is not None and not isinstance(self.metric_note, str):
            raise ValueError("metric_note must be a string or None")


# ---------------------------------------------------------------------------
# Strategy evaluation input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyEvaluationInput:
    """Deterministic strategy-evaluation request (all inputs explicit)."""

    strategy_id: str
    legs: tuple[OptionLeg, ...]
    evaluation_context: EvaluationContext
    reference_timestamp: datetime
    spot: float
    time_to_expiry: float
    risk_free_rate: float
    dividend_yield: float | None = None
    scenario_points: tuple[ScenarioPoint, ...] = ()
    implied_volatility: float | None = None
    payoff: PayoffEvidence | None = None
    market_regime: MarketRegime | None = None
    regime_direction: IntelligenceDirection | None = None
    strategy_direction: IntelligenceDirection | None = None
    liquidity: LiquidityEvidence | None = None
    risk: RiskEvidence | None = None
    historical: HistoricalEvidence | None = None
    opportunity: Opportunity | None = None
    confidence: float | None = None
    quality: QualityResult | None = None
    contract_version: str = STRATEGY_EVALUATION_CONTRACT_VERSION
    model_version: str | None = None
    calculation_version: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.strategy_id, "strategy_id")
        if not isinstance(self.legs, tuple) or not self.legs or not all(
                isinstance(leg, OptionLeg) for leg in self.legs):
            raise ValueError("legs must be a non-empty tuple of OptionLeg")
        if not isinstance(self.evaluation_context, EvaluationContext):
            raise ValueError("evaluation_context must be an EvaluationContext")
        if not _is_aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        _require_finite(self.spot, "spot")
        if self.spot <= 0:
            raise ValueError("spot must be positive")
        _require_finite(self.time_to_expiry, "time_to_expiry")
        if self.time_to_expiry < 0:
            raise ValueError("time_to_expiry must be non-negative")
        _require_finite(self.risk_free_rate, "risk_free_rate")
        _require_finite(self.dividend_yield, "dividend_yield")
        _require_finite(self.implied_volatility, "implied_volatility")
        if self.implied_volatility is not None and self.implied_volatility < 0:
            raise ValueError("implied_volatility must be non-negative or None")
        if not isinstance(self.scenario_points, tuple) or not all(
                isinstance(p, ScenarioPoint) for p in self.scenario_points):
            raise ValueError("scenario_points must be a tuple of ScenarioPoint")
        for point in self.scenario_points:
            for name, value in (("scenario spot", point.spot),
                                ("scenario time_to_expiry",
                                 point.time_to_expiry),
                                ("scenario implied_volatility",
                                 point.implied_volatility)):
                _require_finite(value, name)
            if point.spot <= 0:
                raise ValueError("scenario spot must be positive")
            if point.time_to_expiry < 0:
                raise ValueError("scenario time_to_expiry must be non-negative")
            if point.implied_volatility < 0:
                raise ValueError("scenario implied_volatility must be non-negative")
        if self.market_regime is not None and \
                not isinstance(self.market_regime, MarketRegime):
            raise ValueError("market_regime must be a MarketRegime or None")
        for name in ("regime_direction", "strategy_direction"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, IntelligenceDirection):
                raise ValueError(f"{name} must be an IntelligenceDirection or None")
        if self.payoff is not None and not isinstance(self.payoff, PayoffEvidence):
            raise ValueError("payoff must be a PayoffEvidence or None")
        if self.liquidity is not None and \
                not isinstance(self.liquidity, LiquidityEvidence):
            raise ValueError("liquidity must be a LiquidityEvidence or None")
        if self.risk is not None and not isinstance(self.risk, RiskEvidence):
            raise ValueError("risk must be a RiskEvidence or None")
        if self.historical is not None and \
                not isinstance(self.historical, HistoricalEvidence):
            raise ValueError("historical must be a HistoricalEvidence or None")
        if self.opportunity is not None and \
                not isinstance(self.opportunity, Opportunity):
            raise ValueError("opportunity must be a Day-28 Opportunity or None")
        _require_range(self.confidence, "confidence")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")
        _require_text(self.contract_version, "contract_version")

    @property
    def opportunity_id(self) -> str | None:
        return self.opportunity.opportunity_id if self.opportunity else None


# ---------------------------------------------------------------------------
# Dimension assessments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PayoffAssessment:
    state: DimensionState
    expiry_semantics: PayoffExpirySemantics | None
    net_debit_credit: float | None
    max_profit: float | None
    max_loss: float | None
    tail: TailClass | None
    breakevens: tuple[float, ...]
    note: str


@dataclass(frozen=True)
class GreekAssessment:
    state: DimensionState
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    legs_priced: int
    legs_total: int
    greeks_source: str | None
    note: str


@dataclass(frozen=True)
class ScenarioAssessment:
    state: DimensionState
    points_total: int
    points_assessed: int
    spot_values: tuple[float, ...]
    min_pnl: float | None
    max_pnl: float | None
    unavailable_reasons: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class RegimeAssessment:
    state: DimensionState
    compatibility: RegimeCompatibility | None
    regime_label: RegimeLabel | None
    note: str


@dataclass(frozen=True)
class LiquidityAssessment:
    state: DimensionState
    legs_complete: int | None
    legs_total: int | None
    spread_bps: float | None
    note: str


@dataclass(frozen=True)
class RiskAssessment:
    state: DimensionState
    structural_unbounded_loss: bool | None
    max_loss_estimate: float | None
    informational_only: bool
    note: str


@dataclass(frozen=True)
class HistoricalAssessment:
    state: DimensionState
    observations: int | None
    metric_note: str | None
    note: str


# ---------------------------------------------------------------------------
# Evidence / issues
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationEvidence:
    """One structured evidence row for a dimension assessment."""

    dimension: EvaluationDimension
    state: DimensionState
    source: str
    note: str

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension.value,
            "state": self.state.value,
            "source": self.source,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationEvidence":
        return cls(
            dimension=EvaluationDimension(data["dimension"]),
            state=DimensionState(data["state"]),
            source=data["source"],
            note=data["note"],
        )


@dataclass(frozen=True)
class EvaluationIssue:
    """Structured issue naming the dimension that precluded completeness."""

    dimension: EvaluationDimension
    message: str

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension.value,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationIssue":
        return cls(
            dimension=EvaluationDimension(data["dimension"]),
            message=data["message"],
        )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


class StrategyEvaluationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class StrategyEvaluationResult:
    """Deterministic strategy-evaluation result.

    Contains no order/execution/risk-authorization members.  Confidence
    and Day-12 quality are echoed separately; no single opaque suitability
    number is emitted (each dimension stays inspectable).
    """

    status: StrategyEvaluationStatus
    strategy_id: str
    evaluation_context: EvaluationContext
    reference_timestamp: datetime
    legs: tuple[OptionLeg, ...]
    payoff_assessment: PayoffAssessment
    greek_assessment: GreekAssessment
    scenario_assessment: ScenarioAssessment
    regime_assessment: RegimeAssessment
    liquidity_assessment: LiquidityAssessment
    risk_assessment: RiskAssessment
    historical_assessment: HistoricalAssessment
    evidence: tuple[EvaluationEvidence, ...]
    issues: tuple[EvaluationIssue, ...]
    confidence: float | None
    quality: QualityResult | None
    opportunity_id: str | None
    provenance: Provenance | None
    contract_version: str = STRATEGY_EVALUATION_CONTRACT_VERSION
    model_version: str | None = None
    calculation_version: str | None = None

    def to_dict(self) -> dict:
        payload: dict = {
            "contract": "strategy_evaluation.result",
            "version": self.contract_version,
            "status": self.status.value,
            "strategy_id": self.strategy_id,
            "evaluation_context": self.evaluation_context.value,
            "reference_timestamp": _fmt_ts(self.reference_timestamp),
            "legs": [_leg_to_dict(leg) for leg in self.legs],
            "evidence": [e.to_dict() for e in self.evidence],
            "issues": [i.to_dict() for i in self.issues],
            "confidence": self.confidence,
            "quality": _quality_projection(self.quality),
            "opportunity_id": self.opportunity_id,
            "provenance": _fmt_provenance(self.provenance),
            "model_version": self.model_version,
            "calculation_version": self.calculation_version,
        }
        p = self.payoff_assessment
        payload["payoff_assessment"] = {
            "state": p.state.value,
            "expiry_semantics": p.expiry_semantics.value
            if p.expiry_semantics else None,
            "net_debit_credit": p.net_debit_credit,
            "max_profit": p.max_profit,
            "max_loss": p.max_loss,
            "tail": p.tail.value if p.tail else None,
            "breakevens": list(p.breakevens),
            "note": p.note,
        }
        g = self.greek_assessment
        payload["greek_assessment"] = {
            "state": g.state.value, "delta": g.delta, "gamma": g.gamma,
            "theta": g.theta, "vega": g.vega, "legs_priced": g.legs_priced,
            "legs_total": g.legs_total, "greeks_source": g.greeks_source,
            "note": g.note,
        }
        s = self.scenario_assessment
        payload["scenario_assessment"] = {
            "state": s.state.value, "points_total": s.points_total,
            "points_assessed": s.points_assessed,
            "spot_values": list(s.spot_values), "min_pnl": s.min_pnl,
            "max_pnl": s.max_pnl,
            "unavailable_reasons": list(s.unavailable_reasons), "note": s.note,
        }
        rg = self.regime_assessment
        payload["regime_assessment"] = {
            "state": rg.state.value,
            "compatibility": rg.compatibility.value
            if rg.compatibility else None,
            "regime_label": rg.regime_label.value
            if rg.regime_label else None,
            "note": rg.note,
        }
        lq = self.liquidity_assessment
        payload["liquidity_assessment"] = {
            "state": lq.state.value, "legs_complete": lq.legs_complete,
            "legs_total": lq.legs_total, "spread_bps": lq.spread_bps,
            "note": lq.note,
        }
        rk = self.risk_assessment
        payload["risk_assessment"] = {
            "state": rk.state.value,
            "structural_unbounded_loss": rk.structural_unbounded_loss,
            "max_loss_estimate": rk.max_loss_estimate,
            "informational_only": rk.informational_only, "note": rk.note,
        }
        h = self.historical_assessment
        payload["historical_assessment"] = {
            "state": h.state.value, "observations": h.observations,
            "metric_note": h.metric_note, "note": h.note,
        }
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyEvaluationResult":
        p = data["payoff_assessment"]
        g = data["greek_assessment"]
        s = data["scenario_assessment"]
        rg = data["regime_assessment"]
        lq = data["liquidity_assessment"]
        rk = data["risk_assessment"]
        h = data["historical_assessment"]
        return cls(
            status=StrategyEvaluationStatus(data["status"]),
            strategy_id=data["strategy_id"],
            evaluation_context=EvaluationContext(data["evaluation_context"]),
            reference_timestamp=datetime.fromisoformat(
                data["reference_timestamp"]),
            legs=tuple(_leg_from_dict(x) for x in data["legs"]),
            payoff_assessment=PayoffAssessment(
                state=DimensionState(p["state"]),
                expiry_semantics=PayoffExpirySemantics(p["expiry_semantics"])
                if p.get("expiry_semantics") else None,
                net_debit_credit=p["net_debit_credit"],
                max_profit=p["max_profit"], max_loss=p["max_loss"],
                tail=TailClass(p["tail"]) if p.get("tail") else None,
                breakevens=tuple(p["breakevens"]), note=p["note"]),
            greek_assessment=GreekAssessment(
                state=DimensionState(g["state"]), delta=g["delta"],
                gamma=g["gamma"], theta=g["theta"], vega=g["vega"],
                legs_priced=g["legs_priced"], legs_total=g["legs_total"],
                greeks_source=g.get("greeks_source"), note=g["note"]),
            scenario_assessment=ScenarioAssessment(
                state=DimensionState(s["state"]),
                points_total=s["points_total"],
                points_assessed=s["points_assessed"],
                spot_values=tuple(s["spot_values"]), min_pnl=s["min_pnl"],
                max_pnl=s["max_pnl"],
                unavailable_reasons=tuple(s["unavailable_reasons"]),
                note=s["note"]),
            regime_assessment=RegimeAssessment(
                state=DimensionState(rg["state"]),
                compatibility=RegimeCompatibility(rg["compatibility"])
                if rg.get("compatibility") else None,
                regime_label=RegimeLabel(rg["regime_label"])
                if rg.get("regime_label") else None,
                note=rg["note"]),
            liquidity_assessment=LiquidityAssessment(
                state=DimensionState(lq["state"]),
                legs_complete=lq["legs_complete"], legs_total=lq["legs_total"],
                spread_bps=lq["spread_bps"], note=lq["note"]),
            risk_assessment=RiskAssessment(
                state=DimensionState(rk["state"]),
                structural_unbounded_loss=rk["structural_unbounded_loss"],
                max_loss_estimate=rk["max_loss_estimate"],
                informational_only=rk["informational_only"], note=rk["note"]),
            historical_assessment=HistoricalAssessment(
                state=DimensionState(h["state"]),
                observations=h["observations"], metric_note=h["metric_note"],
                note=h["note"]),
            evidence=tuple(EvaluationEvidence.from_dict(e)
                           for e in data["evidence"]),
            issues=tuple(EvaluationIssue.from_dict(i) for i in data["issues"]),
            confidence=data["confidence"],
            quality=_quality_from_projection(data.get("quality")),
            opportunity_id=data.get("opportunity_id"),
            provenance=_prov_from_dict(data.get("provenance")),
            contract_version=data["version"],
            model_version=data.get("model_version"),
            calculation_version=data.get("calculation_version"),
        )


# ---------------------------------------------------------------------------
# JSON projections
# ---------------------------------------------------------------------------


def _quality_projection(quality: QualityResult | None) -> dict | None:
    if quality is None:
        return None
    return {
        "quality_state": quality.quality_state.value,
        "quality_score": quality.quality_score,
    }


def _quality_from_projection(data: dict | None) -> QualityResult | None:
    if not data:
        return None
    return QualityResult(
        quality_score=int(data["quality_score"]),
        quality_state=QualityState(data["quality_state"]),
        critical_failure=False,
        issues=(),
        dimensions=(),
        evaluated_at=None,
        observation_time=None,
        observation_type="STRATEGY_EVALUATION",
        contract_version="1.0.0",
        reference_time=None,
    )
