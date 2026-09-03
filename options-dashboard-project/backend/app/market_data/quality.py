"""Market Data Quality Engine (Day 12) — the deterministic quality boundary.

Generalizes the GEX-specific quality discipline (``app/services/
gex_data_quality.py``: visible metrics, documented thresholds, machine-
readable output, missing data never converted into valid data) into a
reusable, observation-level engine over the Day-9 canonical contracts:

    Gateway
        → Canonical Observation (QuoteObservation / OptionChainObservation /
                                 MarketObservation)
        → Data Quality Engine
            freshness / completeness / validity / consistency / continuity /
            anomaly / provenance
        → QualityResult (score 0-100, state, structured issues)
        → Quant / Intelligence

Design rules
------------
1. **Determinism.**  ``evaluate(observation, reference_time=...)`` never
   reads the wall clock.  Identical input + reference time ⇒ identical
   result.  ``reference_time`` is the only "current time"; when it is not
   supplied, freshness is NOT_EVALUATED rather than guessed.
2. **No fabrication.**  Missing evidence → ``None``/``NOT_EVALUATED``, never
   an invented value.  Missing optional fields are not issues; missing
   required fields are; structurally impossible checks are not applicable.
3. **Quality ≠ signal.**  No confidence, no market bias, no score-as-
   probability language.  Quality is an input to downstream systems.
4. **No leakage.**  Issues/results never carry credentials or raw broker
   payloads — only canonical field names and safe messages.
5. **Explicit thresholds.**  All thresholds live in :class:`QualityConfig`
   with documented defaults; config is validated at construction.

Score semantics (documented defaults locked by tests)
-----------------------------------------------------
* Dimension weights (evaluated dimensions only): freshness 0.30,
  completeness 0.25, validity 0.20, provenance 0.15, consistency 0.05,
  anomaly 0.05, continuity 0.05 (only when a prior observation is supplied;
  source reliability is NOT_EVALUATED — no justified statistics exist).
* ``quality_score = round(100 * Σ w_d·score_d / Σ w_d)`` over evaluated
  dimensions, each dimension score ∈ [0, 1].
* Classification: EXCELLENT ≥ 90, GOOD ≥ 75, DEGRADED ≥ 60, else
  INSUFFICIENT.  Any CRITICAL-severity issue forces INSUFFICIENT.  Any
  ERROR-severity issue prevents EXCELLENT (GOOD at best).
* Freshness: age ≤ fresh (60s) → 1.0; linear decay to 0 at stale (300s);
  older than stale → 0.0 + ``STALE_OBSERVATION``; future timestamps → 0.0 +
  ``FUTURE_TIMESTAMP``.  Market timestamp preferred; received used only
  when the market timestamp is absent.

No database, no Redis, no workers: a pure assessment layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.market_data.contracts import (
    ContractVersion,
    MarketObservation,
    OptionChainObservation,
    PriceQuote,
    Provenance,
    QualityState,
    QuoteObservation,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class QualityDimension(str, Enum):
    """The quality dimensions assessed by the engine."""

    FRESHNESS = "FRESHNESS"
    COMPLETENESS = "COMPLETENESS"
    VALIDITY = "VALIDITY"
    CONSISTENCY = "CONSISTENCY"
    CONTINUITY = "CONTINUITY"
    ANOMALY = "ANOMALY"
    PROVENANCE = "PROVENANCE"
    SOURCE_RELIABILITY = "SOURCE_RELIABILITY"


class QualityIssueCode(str, Enum):
    """Structured, machine-readable quality issue categories."""

    STALE_OBSERVATION = "STALE_OBSERVATION"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_VOLUME = "INVALID_VOLUME"
    INVALID_OI = "INVALID_OI"
    INVALID_STRIKE = "INVALID_STRIKE"
    INVALID_EXPIRY = "INVALID_EXPIRY"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    BID_ASK_INCONSISTENT = "BID_ASK_INCONSISTENT"
    OHLC_INCONSISTENT = "OHLC_INCONSISTENT"
    TIMESTAMP_ORDER = "TIMESTAMP_ORDER"
    CHAIN_INCOMPLETE = "CHAIN_INCOMPLETE"
    CONTINUITY_BREAK = "CONTINUITY_BREAK"
    ANOMALOUS_VALUE = "ANOMALOUS_VALUE"


class IssueSeverity(str, Enum):
    """Severity of a quality issue.

    CRITICAL forces the overall state to INSUFFICIENT.  ERROR prevents
    EXCELLENT (quality-relevant but recoverable).  WARNING is informational
    (visible, does not lower the dimension score).
    """

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketDataQualityConfig:
    """Deterministic quality thresholds (documented defaults)."""

    # Freshness (seconds).
    fresh_seconds: float = 60.0      # age ≤ fresh → freshness score 1.0
    stale_seconds: float = 300.0     # age ≥ stale → freshness score 0.0 + STALE
    # Structural anomaly magnitude bounds.
    max_abs_price: float = 10_000_000.0
    max_volume: float = 1_000_000_000_000.0
    max_oi: float = 10_000_000_000.0
    # Continuity: max acceptable |Δ|/prev relative jump (1.0 = 100%).
    max_relative_jump: float = 1.0

    def __post_init__(self) -> None:
        if self.fresh_seconds <= 0:
            raise ValueError("fresh_seconds must be positive")
        if self.stale_seconds < self.fresh_seconds:
            raise ValueError("stale_seconds must be >= fresh_seconds")
        if self.max_abs_price <= 0 or self.max_volume <= 0 or self.max_oi <= 0:
            raise ValueError("magnitude bounds must be positive")
        if self.max_relative_jump < 0:
            raise ValueError("max_relative_jump must be >= 0")


# Documented dimension weights (defaults, locked by tests).
DIMENSION_WEIGHTS: dict[QualityDimension, float] = {
    QualityDimension.FRESHNESS: 0.30,
    QualityDimension.COMPLETENESS: 0.25,
    QualityDimension.VALIDITY: 0.20,
    QualityDimension.CONSISTENCY: 0.05,
    QualityDimension.PROVENANCE: 0.15,
    QualityDimension.ANOMALY: 0.05,
    QualityDimension.CONTINUITY: 0.05,
}

# Classification thresholds (documented, locked by tests).
_SCORE_EXCELLENT = 90
_SCORE_GOOD = 75
_SCORE_DEGRADED = 60


def classify(score: int, critical: bool) -> QualityState:
    """Map a bounded 0-100 score (+ critical flag) to a quality state.

    A CRITICAL-severity issue forces INSUFFICIENT regardless of score —
    critical failures must never produce an EXCELLENT-looking result.
    """
    if critical:
        return QualityState.INSUFFICIENT
    if score >= _SCORE_EXCELLENT:
        return QualityState.EXCELLENT
    if score >= _SCORE_GOOD:
        return QualityState.GOOD
    if score >= _SCORE_DEGRADED:
        return QualityState.DEGRADED
    return QualityState.INSUFFICIENT


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityIssue:
    """One structured quality issue.

    ``dimension`` is the :class:`QualityDimension` that raised it, ``code``
    a :class:`QualityIssueCode`, ``severity`` an :class:`IssueSeverity`,
    ``field`` the canonical field concerned (never a broker key), and
    ``message`` a safe human-readable description (never a credential, never
    a raw broker payload).
    """

    dimension: QualityDimension
    code: QualityIssueCode
    severity: IssueSeverity
    message: str
    field: str | None = None


@dataclass(frozen=True)
class DimensionResult:
    """Score and issues for one dimension.

    ``status`` is ``EVALUATED`` when the observation supplied enough
    evidence for the dimension, else ``NOT_EVALUATED`` (explicitly — the
    engine never fabricates a score).  ``score`` is None when
    NOT_EVALUATED, else a 0..1 fraction.
    """

    dimension: QualityDimension
    status: str  # EVALUATED | NOT_EVALUATED
    score: float | None = None
    issues: tuple[QualityIssue, ...] = ()


@dataclass(frozen=True)
class QualityResult:
    """Complete quality assessment of one canonical observation.

    ``quality_score`` is a bounded integer 0-100 — a quality index, never a
    probability and never a confidence/signal measure.  ``evaluated_at`` is
    the reference time used (None when none was supplied); ``observation_time``
    is the observation's market timestamp (received as fallback).
    """

    quality_score: int
    quality_state: QualityState
    critical_failure: bool
    issues: tuple[QualityIssue, ...]
    dimensions: tuple[DimensionResult, ...]
    evaluated_at: datetime | None
    observation_time: datetime | None
    observation_type: str
    contract_version: str | None
    reference_time: datetime | None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_EVALUATED = "EVALUATED"
_NOT_EVALUATED = "NOT_EVALUATED"


def _issue(
    dim: QualityDimension,
    code: QualityIssueCode,
    severity: IssueSeverity,
    message: str,
    field: str | None = None,
) -> QualityIssue:
    return QualityIssue(dim, code, severity, message, field)


def _aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _fraction(passes: int, total: int) -> float:
    return 1.0 if total == 0 else passes / total


class MarketDataQualityEngine:
    """Deterministic quality assessment over Day-9 canonical observations.

    Pure and side-effect free: no DB, no I/O, no wall clock.  ``evaluate``
    takes an explicit ``reference_time`` (the only notion of "now") and an
    optional ``previous`` observation for continuity comparison.
    """

    def __init__(self, config: MarketDataQualityConfig | None = None):
        self._config = config or MarketDataQualityConfig()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def evaluate(
        self,
        observation,
        *,
        reference_time: datetime | None = None,
        previous=None,
    ) -> QualityResult:
        if reference_time is not None and not _aware(reference_time):
            raise ValueError("reference_time must be a timezone-aware datetime")

        if isinstance(observation, QuoteObservation):
            return self._evaluate_quote(observation, reference_time, previous)
        if isinstance(observation, OptionChainObservation):
            return self._evaluate_chain(observation, reference_time, previous)
        if isinstance(observation, MarketObservation):
            return self._evaluate_market(observation, reference_time, previous)
        raise ValueError(
            "Unsupported observation type for quality evaluation; expected a "
            "Day-9 canonical observation (QuoteObservation, "
            "OptionChainObservation or MarketObservation)."
        )

    # ------------------------------------------------------------------
    # Shared assembly
    # ------------------------------------------------------------------

    def _assemble(
        self,
        dimensions: list[DimensionResult],
        *,
        reference_time: datetime | None,
        observation_time: datetime | None,
        observation_type: str,
        contract_version,
    ) -> QualityResult:
        evaluated = [d for d in dimensions if d.status == _EVALUATED]
        denom = sum(DIMENSION_WEIGHTS[d.dimension] for d in evaluated)
        numerator = sum(
            DIMENSION_WEIGHTS[d.dimension] * (d.score or 0.0) for d in evaluated
        )
        composite = 100.0 * (numerator / denom) if denom else 100.0
        score = max(0, min(100, int(round(composite))))

        issues = tuple(
            issue for d in dimensions for issue in d.issues
        )
        critical = any(i.severity is IssueSeverity.CRITICAL for i in issues)
        state = classify(score, critical)
        # An ERROR-severity issue must never sit inside an EXCELLENT result.
        if state is QualityState.EXCELLENT and any(
            i.severity is IssueSeverity.ERROR for i in issues
        ):
            state = QualityState.GOOD

        return QualityResult(
            quality_score=score,
            quality_state=state,
            critical_failure=critical,
            issues=issues,
            dimensions=tuple(dimensions),
            evaluated_at=reference_time,
            observation_time=observation_time,
            observation_type=observation_type,
            contract_version=_version_value(contract_version),
            reference_time=reference_time,
        )

    # ------------------------------------------------------------------
    # QuoteObservation
    # ------------------------------------------------------------------

    def _evaluate_quote(self, obs: QuoteObservation, reference_time, previous):
        dimensions = []
        dimensions.append(self._freshness_dim(obs, reference_time))
        dimensions.append(self._quote_completeness(obs))
        dimensions.append(self._validity_dim(
            [obs.quote] if obs.quote is not None else [],
            timestamps=(obs.received_timestamp, obs.market_timestamp),
            expiry=None,
            strikes=(),
            obs_label="quote",
        ))
        dimensions.append(self._consistency_dim(
            [obs.quote] if obs.quote is not None else [],
            market_ts=obs.market_timestamp,
            received_ts=obs.received_timestamp,
        ))
        dimensions.append(self._continuity_dim(
            current=obs, previous=previous, mode_key="quote"
        ))
        dimensions.append(self._anomaly_dim(
            [obs.quote] if obs.quote is not None else [],
            spot=None,
            strikes=(),
        ))
        dimensions.append(self._provenance_object_dim(
            obs.provenance, data_mode=obs.data_mode
        ))
        dimensions.append(self._not_evaluated(QualityDimension.SOURCE_RELIABILITY))
        return self._assemble(
            dimensions,
            reference_time=reference_time,
            observation_time=_pick_observation_time(obs),
            observation_type="QuoteObservation",
            contract_version=obs.contract_version,
        )

    def _quote_completeness(self, obs: QuoteObservation) -> DimensionResult:
        issues: list[QualityIssue] = []
        checks = [
            (bool(obs.instrument) and bool(getattr(obs.instrument, "symbol", "")),
             "instrument.symbol"),
            (obs.quote is not None and obs.quote.ltp is not None, "quote.ltp"),
            (obs.received_timestamp is not None, "received_timestamp"),
            (bool(obs.source), "source"),
        ]
        passes = 0
        for ok, field in checks:
            if ok:
                passes += 1
            else:
                issues.append(_issue(
                    QualityDimension.COMPLETENESS,
                    QualityIssueCode.MISSING_REQUIRED_FIELD,
                    IssueSeverity.ERROR,
                    f"Quote is missing required field '{field}'.",
                    field=field,
                ))
        return DimensionResult(
            QualityDimension.COMPLETENESS, _EVALUATED,
            _fraction(passes, len(checks)), tuple(issues),
        )

    # ------------------------------------------------------------------
    # OptionChainObservation
    # ------------------------------------------------------------------

    def _evaluate_chain(self, obs: OptionChainObservation, reference_time, previous):
        dimensions = []
        dimensions.append(self._freshness_dim(obs, reference_time))
        dimensions.append(self._chain_completeness(obs))
        legs = [leg for row in obs.chain for leg in (row.call, row.put) if leg is not None]
        dimensions.append(self._validity_dim(
            legs,
            timestamps=(obs.received_timestamp, obs.market_timestamp),
            expiry=obs.expiry_date,
            strikes=tuple(row.strike for row in obs.chain),
            obs_label="chain",
        ))
        dimensions.append(self._consistency_dim(
            legs,
            market_ts=obs.market_timestamp,
            received_ts=obs.received_timestamp,
        ))
        dimensions.append(self._continuity_dim(
            current=obs, previous=previous, mode_key="chain"
        ))
        dimensions.append(self._anomaly_dim(
            legs,
            spot=obs.underlying_spot_price,
            strikes=tuple(row.strike for row in obs.chain),
        ))
        dimensions.append(self._flattened_provenance_dim(
            data_mode=obs.data_mode,
            flattened_source=obs.source,
            flattened_received=obs.received_timestamp,
            flattened_contract=obs.contract_version,
        ))
        dimensions.append(self._not_evaluated(QualityDimension.SOURCE_RELIABILITY))
        return self._assemble(
            dimensions,
            reference_time=reference_time,
            observation_time=_pick_observation_time(obs),
            observation_type="OptionChainObservation",
            contract_version=obs.contract_version,
        )

    def _chain_completeness(self, obs: OptionChainObservation) -> DimensionResult:
        issues: list[QualityIssue] = []
        has_rows = len(obs.chain) > 0
        spot_ok = obs.underlying_spot_price is not None

        checks = [
            (bool(obs.symbol), "symbol"),
            (bool(obs.expiry_date), "expiry_date"),
            (has_rows, "chain"),
            (spot_ok, "underlying_spot_price"),
        ]
        passes = 0
        for ok, field in checks:
            if ok:
                passes += 1
            elif field == "chain":
                issues.append(_issue(
                    QualityDimension.COMPLETENESS,
                    QualityIssueCode.CHAIN_INCOMPLETE,
                    IssueSeverity.CRITICAL,
                    "Option chain has no rows — nothing usable downstream.",
                    field="chain",
                ))
            else:
                issues.append(_issue(
                    QualityDimension.COMPLETENESS,
                    QualityIssueCode.MISSING_REQUIRED_FIELD,
                    IssueSeverity.ERROR,
                    f"Chain is missing required field '{field}'.",
                    field=field,
                ))

        # A row with neither leg is incomplete (warning only — the row is
        # structurally unusable but does not invalidate the chain).
        for row in obs.chain:
            if row.call is None and row.put is None:
                issues.append(_issue(
                    QualityDimension.COMPLETENESS,
                    QualityIssueCode.CHAIN_INCOMPLETE,
                    IssueSeverity.WARNING,
                    f"Chain row at strike {row.strike} has no call or put leg.",
                    field="chain",
                ))
        return DimensionResult(
            QualityDimension.COMPLETENESS, _EVALUATED,
            _fraction(passes, len(checks)), tuple(issues),
        )

    # ------------------------------------------------------------------
    # MarketObservation
    # ------------------------------------------------------------------

    def _evaluate_market(self, obs: MarketObservation, reference_time, previous):
        issues: list[QualityIssue] = []
        checks = [
            (bool(obs.instrument) and bool(getattr(obs.instrument, "symbol", "")),
             "instrument.symbol"),
            (obs.market_timestamp is not None, "market_timestamp"),
            (obs.received_timestamp is not None, "received_timestamp"),
            (bool(obs.source), "source"),
        ]
        passes = 0
        for ok, field in checks:
            if ok:
                passes += 1
            else:
                issues.append(_issue(
                    QualityDimension.COMPLETENESS,
                    QualityIssueCode.MISSING_REQUIRED_FIELD,
                    IssueSeverity.ERROR,
                    f"Observation is missing required field '{field}'.",
                    field=field,
                ))
        dims = [
            self._freshness_dim(obs, reference_time),
            DimensionResult(QualityDimension.COMPLETENESS, _EVALUATED,
                            _fraction(passes, len(checks)), tuple(issues)),
            self._not_evaluated(QualityDimension.VALIDITY),
            self._not_evaluated(QualityDimension.CONSISTENCY),
            self._continuity_dim(current=obs, previous=previous, mode_key="market"),
            self._not_evaluated(QualityDimension.ANOMALY),
            self._provenance_object_dim(obs.provenance, data_mode=obs.data_mode),
            self._not_evaluated(QualityDimension.SOURCE_RELIABILITY),
        ]
        return self._assemble(
            dims,
            reference_time=reference_time,
            observation_time=_pick_observation_time(obs),
            observation_type="MarketObservation",
            contract_version=obs.contract_version,
        )

    # ------------------------------------------------------------------
    # Dimension implementations (shared)
    # ------------------------------------------------------------------

    def _freshness_dim(self, obs, reference_time) -> DimensionResult:
        dim = QualityDimension.FRESHNESS
        market = getattr(obs, "market_timestamp", None)
        received = getattr(obs, "received_timestamp", None)
        ts = market if market is not None else received
        if reference_time is None or ts is None:
            issues = ()
            if reference_time is not None and ts is None:
                issues = (_issue(
                    dim, QualityIssueCode.MISSING_TIMESTAMP,
                    IssueSeverity.WARNING,
                    "Observation has no timestamp to evaluate freshness against.",
                    field="received_timestamp",
                ),)
            return DimensionResult(dim, _NOT_EVALUATED, None, issues)
        if not _aware(ts):
            # Naive timestamps are flagged in validity; freshness cannot be
            # computed against an aware reference without guessing a zone.
            return DimensionResult(dim, _NOT_EVALUATED, None, ())
        age = (reference_time - ts).total_seconds()
        if age < 0:
            return DimensionResult(dim, _EVALUATED, 0.0, (_issue(
                dim, QualityIssueCode.FUTURE_TIMESTAMP, IssueSeverity.ERROR,
                f"Observation timestamp {ts.isoformat()} is in the future "
                f"relative to reference {reference_time.isoformat()} — never "
                "silently treated as fresh.",
                field="market_timestamp" if market is not None else "received_timestamp",
            ),))
        cfg = self._config
        if age <= cfg.fresh_seconds:
            return DimensionResult(dim, _EVALUATED, 1.0, ())
        if age >= cfg.stale_seconds:
            return DimensionResult(dim, _EVALUATED, 0.0, (_issue(
                dim, QualityIssueCode.STALE_OBSERVATION, IssueSeverity.ERROR,
                f"Observation is {age:.0f}s old (stale limit "
                f"{cfg.stale_seconds:.0f}s).",
            ),))
        score = 1.0 - (age - cfg.fresh_seconds) / (cfg.stale_seconds - cfg.fresh_seconds)
        return DimensionResult(dim, _EVALUATED, score, ())

    def _validity_dim(self, prices, *, timestamps, expiry, strikes,
                      obs_label: str) -> DimensionResult:
        """Structural validity: every applicable condition is scored (pass or
        fail).  A negative price is CRITICAL; the other invalid values are
        ERROR-severity issues."""
        dim = QualityDimension.VALIDITY
        # (ok, code, severity, fail-message, field)
        checks: list[tuple[bool, QualityIssueCode, IssueSeverity, str, str | None]] = []
        for price in prices:
            if price is None:
                continue
            checks.append((price.ltp >= 0, QualityIssueCode.INVALID_PRICE,
                           IssueSeverity.CRITICAL,
                           "Negative last traded price.", "ltp"))
            for field, value in (("bid", price.bid), ("ask", price.ask),
                                 ("open", price.open), ("high", price.high),
                                 ("low", price.low), ("close", price.close)):
                if value is not None:
                    checks.append((value >= 0, QualityIssueCode.INVALID_PRICE,
                                   IssueSeverity.ERROR,
                                   f"Negative {field} value.", field))
            if price.volume is not None:
                checks.append((price.volume >= 0,
                               QualityIssueCode.INVALID_VOLUME,
                               IssueSeverity.ERROR, "Negative volume.",
                               "volume"))
            if price.oi is not None:
                checks.append((price.oi >= 0, QualityIssueCode.INVALID_OI,
                               IssueSeverity.ERROR, "Negative open interest.",
                               "oi"))
        for strike in strikes:
            if strike is not None:
                checks.append((strike > 0, QualityIssueCode.INVALID_STRIKE,
                               IssueSeverity.ERROR,
                               "Strike must be positive.", "strike"))
        if expiry is not None:
            try:
                datetime.strptime(str(expiry), "%Y-%m-%d")
                valid_expiry = True
            except ValueError:
                valid_expiry = False
            checks.append((valid_expiry, QualityIssueCode.INVALID_EXPIRY,
                           IssueSeverity.ERROR,
                           f"Expiry '{expiry}' is not a valid YYYY-MM-DD date.",
                           "expiry_date"))
        for ts, name in zip(timestamps, ("received_timestamp", "market_timestamp")):
            if ts is not None:
                checks.append((_aware(ts), QualityIssueCode.INVALID_TIMESTAMP,
                               IssueSeverity.ERROR,
                               f"{name} is not timezone-aware — cannot be "
                               "normalized to UTC.", name))
        issues = []
        passes = 0
        for ok, code, severity, message, field in checks:
            if ok:
                passes += 1
            else:
                issues.append(_issue(dim, code, severity, message, field))
        if not checks:
            return DimensionResult(dim, _NOT_EVALUATED, None, ())
        return DimensionResult(dim, _EVALUATED, _fraction(passes, len(checks)),
                               tuple(issues))

    def _consistency_dim(self, prices, *, market_ts, received_ts) -> DimensionResult:
        dim = QualityDimension.CONSISTENCY
        checks: list[tuple[bool, QualityIssueCode, IssueSeverity, str, str | None]] = []
        # No applicable relational checks → nothing to flag: vacuous full score.
        for price in prices:
            if price is None:
                continue
            if price.bid is not None and price.ask is not None and price.bid > price.ask:
                checks.append((False, QualityIssueCode.BID_ASK_INCONSISTENT,
                               IssueSeverity.ERROR,
                               "Bid is above ask.", "bid"))
            if (price.low is not None and price.high is not None
                    and price.low > price.high):
                checks.append((False, QualityIssueCode.OHLC_INCONSISTENT,
                               IssueSeverity.ERROR,
                               "Low is above high.", "low"))
            if (price.low is not None and price.high is not None
                    and not (price.low <= price.ltp <= price.high)):
                checks.append((False, QualityIssueCode.OHLC_INCONSISTENT,
                               IssueSeverity.ERROR,
                               "LTP lies outside the low/high range.", "ltp"))
        issues = []
        passes = 0
        for ok, code, severity, message, field in checks:
            if ok:
                passes += 1
            else:
                issues.append(_issue(dim, code, severity, message, field))
        # Timestamp ordering: an event time after the receive time is
        # impossible under sane clocks — warning, not a scoring failure.
        order_issues: list[QualityIssue] = []
        if market_ts is not None and received_ts is not None and _aware(market_ts) \
                and _aware(received_ts) and market_ts > received_ts:
            order_issues.append(_issue(
                dim, QualityIssueCode.TIMESTAMP_ORDER, IssueSeverity.WARNING,
                "Market/event timestamp is after the received timestamp.",
                "market_timestamp",
            ))
        if not checks:
            return DimensionResult(dim, _EVALUATED, 1.0,
                                   tuple(order_issues))
        return DimensionResult(dim, _EVALUATED, _fraction(passes, len(checks)),
                               tuple(issues) + tuple(order_issues))

    def _anomaly_dim(self, prices, *, spot, strikes) -> DimensionResult:
        """Deterministic structural anomaly checks: documented magnitude
        bounds from :class:`MarketDataQualityConfig`.  Not statistical — no
        distribution assumptions, no ML."""
        dim = QualityDimension.ANOMALY
        cfg = self._config
        checks: list[tuple[bool, QualityIssueCode, IssueSeverity, str, str | None]] = []
        for price in prices:
            if price is None:
                continue
            checks.append((price.ltp <= cfg.max_abs_price,
                           QualityIssueCode.ANOMALOUS_VALUE,
                           IssueSeverity.ERROR,
                           f"LTP {price.ltp} exceeds the documented magnitude "
                           f"bound {cfg.max_abs_price:g}.", "ltp"))
            if price.volume is not None:
                checks.append((price.volume <= cfg.max_volume,
                               QualityIssueCode.ANOMALOUS_VALUE,
                               IssueSeverity.ERROR,
                               "Volume exceeds the documented magnitude "
                               "bound.", "volume"))
            if price.oi is not None:
                checks.append((price.oi <= cfg.max_oi,
                               QualityIssueCode.ANOMALOUS_VALUE,
                               IssueSeverity.ERROR,
                               "Open interest exceeds the documented "
                               "magnitude bound.", "oi"))
        if spot is not None:
            checks.append((abs(spot) <= cfg.max_abs_price,
                           QualityIssueCode.ANOMALOUS_VALUE,
                           IssueSeverity.ERROR,
                           "Underlying spot exceeds the documented magnitude "
                           "bound.", "underlying_spot_price"))
        for strike in strikes:
            if strike is not None:
                checks.append((abs(strike) <= cfg.max_abs_price,
                               QualityIssueCode.ANOMALOUS_VALUE,
                               IssueSeverity.ERROR,
                               "Strike exceeds the documented magnitude "
                               "bound.", "strike"))
        issues = []
        passes = 0
        for ok, code, severity, message, field in checks:
            if ok:
                passes += 1
            else:
                issues.append(_issue(dim, code, severity, message, field))
        return DimensionResult(dim, _EVALUATED, _fraction(passes, len(checks)),
                               tuple(issues))

    def _provenance_object_dim(self, prov: Provenance | None, *,
                               data_mode) -> DimensionResult:
        """Assess provenance for observations that carry a
        :class:`Provenance` object (quotes, market observations).

        Provenance is MANDATORY on the canonical boundary (Day-9 rule 8): a
        quote/market observation with no provenance at all is a CRITICAL
        failure even when every other field is perfect.
        """
        dim = QualityDimension.PROVENANCE
        if prov is None:
            return DimensionResult(dim, _EVALUATED, 0.0, (_issue(
                dim, QualityIssueCode.INVALID_PROVENANCE, IssueSeverity.CRITICAL,
                "Observation carries no provenance — cannot answer where / "
                "when / how the data was produced.",
            ),))
        return self._provenance_parts_dim(prov, data_mode)

    @staticmethod
    def _flattened_provenance_dim(*, data_mode, flattened_source,
                                  flattened_received,
                                  flattened_contract) -> DimensionResult:
        """Assess provenance for option chains, which carry provenance-
        flattened observation fields (source / data_mode / received time /
        contract version) instead of a :class:`Provenance` object."""
        dim = QualityDimension.PROVENANCE
        present = {
            "source": bool(flattened_source),
            "data_mode": data_mode is not None,
            "received_timestamp": _aware(flattened_received),
            "contract_version": bool(flattened_contract),
        }
        if not any(present.values()):
            return DimensionResult(dim, _EVALUATED, 0.0, (_issue(
                dim, QualityIssueCode.INVALID_PROVENANCE, IssueSeverity.CRITICAL,
                "Observation carries no traceable provenance (no source, "
                "mode, receive time or contract version).",
            ),))
        issues = []
        passes = 0
        for field, ok in present.items():
            if ok:
                passes += 1
            else:
                issues.append(_issue(
                    dim, QualityIssueCode.INVALID_PROVENANCE, IssueSeverity.ERROR,
                    f"Provenance is missing '{field}'.", field=field,
                ))
        return DimensionResult(dim, _EVALUATED, _fraction(passes, len(present)),
                               tuple(issues))

    @staticmethod
    def _provenance_parts_dim(prov: Provenance, data_mode) -> DimensionResult:
        dim = QualityDimension.PROVENANCE
        parts = {
            "source": bool(prov.source),
            "collection_mode": bool(prov.collection_mode),
            "received_at": _aware(prov.received_at),
            "normalization_version": bool(prov.normalization_version),
            "contract_version": bool(prov.contract_version),
        }
        issues = []
        passes = 0
        for field, ok in parts.items():
            if ok:
                passes += 1
            else:
                issues.append(_issue(
                    dim, QualityIssueCode.INVALID_PROVENANCE, IssueSeverity.ERROR,
                    f"Provenance is missing '{field}'.", field=field,
                ))
        total = len(parts)
        coherence_applicable = data_mode is not None and bool(prov.collection_mode)
        if coherence_applicable:
            total += 1
            mode_value = getattr(data_mode, "value", data_mode)
            if prov.collection_mode == mode_value:
                passes += 1
            else:
                issues.append(_issue(
                    dim, QualityIssueCode.INVALID_PROVENANCE, IssueSeverity.ERROR,
                    f"Provenance collection_mode '{prov.collection_mode}' "
                    f"contradicts the observation data_mode '{mode_value}'.",
                    field="collection_mode",
                ))
        return DimensionResult(dim, _EVALUATED, _fraction(passes, total),
                               tuple(issues))

    def _continuity_dim(self, *, current, previous, mode_key: str) -> DimensionResult:
        dim = QualityDimension.CONTINUITY
        if previous is None:
            return self._not_evaluated(dim)
        prev_inst = getattr(previous, "instrument", None)
        cur_inst = getattr(current, "instrument", None)
        if prev_inst != cur_inst:
            raise ValueError(
                "Continuity comparison requires the previous observation to "
                "match the current instrument."
            )
        current_price = _comparable_price(current)
        previous_price = _comparable_price(previous)
        if current_price is None or previous_price is None or previous_price <= 0:
            # No single positive comparable value → no evidence to compare.
            return self._not_evaluated(dim)
        jump = abs(current_price - previous_price) / previous_price
        if jump > self._config.max_relative_jump:
            return DimensionResult(dim, _EVALUATED, 0.0, (_issue(
                dim, QualityIssueCode.CONTINUITY_BREAK, IssueSeverity.ERROR,
                f"Relative jump of {jump:.0%} exceeds the documented "
                f"limit of {self._config.max_relative_jump:.0%}.",
                field="ltp",
            ),))
        return DimensionResult(dim, _EVALUATED, 1.0, ())

    @staticmethod
    def _not_evaluated(dim: QualityDimension) -> DimensionResult:
        return DimensionResult(dim, _NOT_EVALUATED, None, ())


def _pick_observation_time(obs):
    return getattr(obs, "market_timestamp", None) or getattr(
        obs, "received_timestamp", None
    )


def _version_value(contract_version) -> str | None:
    if contract_version is None:
        return None
    if isinstance(contract_version, ContractVersion):
        return contract_version.value
    return str(contract_version)


def _comparable_price(obs) -> float | None:
    """A single comparable numeric for continuity: the LTP for quotes, the
    underlying spot for chains (spot may be None)."""
    quote = getattr(obs, "quote", None)
    if quote is not None:
        return getattr(quote, "ltp", None)
    return getattr(obs, "underlying_spot_price", None)
