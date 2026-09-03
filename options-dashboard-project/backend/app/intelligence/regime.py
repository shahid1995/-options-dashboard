"""Day 23 — Market Regime Engine.

Deterministic, broker-neutral market-regime classification on the Day-19
Intelligence Contract, consuming the evidence surfaces of Days 20–22::

    price-window / volatility / positioning / institutional / level evidence
        -> deterministic regime classification (priority cascade)
        -> one Day-19 IntelligenceResult with MarketRegime attached

The regime travels in the typed Day-19 channel (``result.regime`` is a
:class:`MarketRegime` whose ``label`` is a :class:`RegimeLabel` —
TRENDING / RANGING / HIGH_VOLATILITY / LOW_VOLATILITY / RISK_ON / RISK_OFF /
UNKNOWN).  Outputs are structural market-state reads only — no participant or
institution identity claims, no fabricated historical evidence.

Classification priority (documented; exactly one label per evaluation)
----------------------------------------------------------------------
1. **Conflicting evidence** — a usable price direction plus any opposing
   source (Day-20 positioning label, Day-22 institutional direction — a MIXED
   institutional read counts as opposing — or a proximate Day-21
   CONFLICTED_INTERACTION level) => ``PARTIAL`` + ``MIXED`` +
   ``CONFLICTING_DIRECTION`` + regime ``UNKNOWN``.  Conflicts are never hidden
   inside a clean regime read.
2. **TRENDING** — actual directional price-window evidence:
   >= ``TREND_MIN_MOVES`` nonzero moves, all the same sign (measured flats
   allowed).  A single price observation is never a trend.
3. **RANGING** — bounded non-directional price-window evidence:
   >= ``RANGE_MIN_MOVES`` moves with both signs and
   ``net_fraction <= RANGING_MAX_NET_FRACTION``.  "No trend" alone never
   becomes RANGING.
4. **HIGH_VOLATILITY** — explicit ``volatility > HIGH_VOLATILITY_THRESHOLD``
   (annualized fraction).  Never manufactured from a single price
   observation; a missing volatility measure makes the vol regimes
   unreachable.
5. **LOW_VOLATILITY** — explicit ``volatility < LOW_VOLATILITY_THRESHOLD``.
6. **RISK_ON / RISK_OFF** — a usable price direction, no opposing source, and
   at least one corroborating directional source (positioning /
   institutional / level).  Positioning or institutional evidence alone is
   never a regime claim — price evidence is mandatory.
7. **UNKNOWN** — usable evidence present but nothing above classified:
   ``SUCCESS`` + ``direction = UNKNOWN`` + regime ``UNKNOWN`` + strength 0.0
   (an honest measured "cannot classify", never a fabricated regime).

Rules
-----
1. Missing stays ``None`` — never coerced to zero; a measured 0.0 stays a
   legitimate zero.  SUCCESS rests only on present, finite evidence.
2. ``signal_strength != confidence != quality`` — separate fields; the exact
   Day-12 :class:`QualityResult` and Day-9 :class:`Provenance` are preserved
   verbatim; quality is never recomputed.
3. All thresholds and references are documented constants — no hidden weights.
4. Pure and deterministic: no wall clock, randomness, network, filesystem,
   database, broker or services imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.market_data.contracts import Provenance
from app.market_data.quality import QualityResult, QualityState
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
from app.intelligence.levels import LevelClassification, LevelKind, LevelState
from app.intelligence.positioning import PositioningClassification, classification_direction

# ---------------------------------------------------------------------------
# Identity / versioning / documented policy constants
# ---------------------------------------------------------------------------

CALCULATION_ID = "intelligence.regime.v1"
MODEL_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"

#: Minimum number of same-sign nonzero price moves for TRENDING.
TREND_MIN_MOVES = 3

#: Minimum number of price moves for RANGING.
RANGE_MIN_MOVES = 3

#: |net| / gross price-window fraction at or below which a both-signed window
#: is considered bounded / non-directional (RANGING).
RANGING_MAX_NET_FRACTION = 0.25

#: Explicit annualized volatility bounds (fractions): strictly above the high
#: threshold => HIGH_VOLATILITY; strictly below the low threshold =>
#: LOW_VOLATILITY; boundaries are exclusive (documented and boundary-tested).
HIGH_VOLATILITY_THRESHOLD = 0.30
LOW_VOLATILITY_THRESHOLD = 0.15

#: A classified level is "proximate" when its strike is within this fraction
#: of spot (same documented rule as Day 22).
LEVEL_PROXIMITY_FRACTION = 0.10

#: Opposition magnitude reference when an opposing source carries no measured
#: magnitude (documented; the Day-19 contract requires a positive strength
#: for the MIXED directional claim).
CONFLICT_DEFAULT_STRENGTH = 0.5

#: Documented deterministic confidence table (completeness-based).
CONFIDENCE_TREND = 0.90
CONFIDENCE_RANGE = 0.90
CONFIDENCE_VOLATILITY = 0.85
CONFIDENCE_RISK_FULL = 0.90   # >= 2 corroborating sources
CONFIDENCE_RISK_MINIMAL = 0.75  # exactly one corroborating source
CONFIDENCE_CONFLICT = 0.50
CONFIDENCE_UNKNOWN = 0.40


# ---------------------------------------------------------------------------
# Vocabulary / helpers
# ---------------------------------------------------------------------------


class _PriceWindow(Enum):
    """Internal price-window reading (deterministic)."""

    TRENDING = "TRENDING"
    RANGING = "RANGING"
    NONE = "NONE"


def _require_text(value: str | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _finite_or_none(value, name: str) -> None:
    if value is not None and (
        not isinstance(value, (int, float)) or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number or None")


def _non_negative_or_none(value, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _range_or_none(value, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0]")


def _aware(ts: datetime | None) -> bool:
    return ts is not None and ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None


def _sign(value: float) -> int:
    return 1 if value > 0 else -1


# ---------------------------------------------------------------------------
# Raw input layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeInput:
    """Canonical input to the market-regime engine for one underlying.

    Evidence is caller-supplied from the existing contracts: ``price_moves``
    is an ordered tuple of signed price changes over the evaluation window
    (from canonical price observations — never read from a wall clock);
    ``volatility`` is an explicit annualized volatility fraction from the
    Day-15/16 quant surface (e.g. an ATMF implied-volatility reference);
    ``positioning`` is the Day-20 :class:`PositioningClassification` label;
    ``institutional_direction``/``institutional_strength`` come from the
    Day-22 result; ``level_classifications`` are Day-21 typed rows.  Missing
    stays ``None`` (never coerced to zero); timestamps are explicit and
    genuinely timezone-aware; ``quality`` is the preserved Day-12 assessment.
    """

    underlying: str
    reference_timestamp: datetime
    provenance: Provenance
    expiry: str | None = None
    spot: float | None = None
    spot_change: float | None = None
    window_seconds: float | None = None
    price_moves: tuple[float, ...] = ()
    volatility: float | None = None
    positioning: PositioningClassification | None = None
    institutional_direction: IntelligenceDirection | None = None
    institutional_strength: float | None = None
    level_classifications: tuple[LevelClassification, ...] = ()
    quality: QualityResult | None = None

    def __post_init__(self) -> None:
        _require_text(self.underlying, "underlying")
        if self.expiry is not None:
            _require_text(self.expiry, "expiry")
        _finite_or_none(self.spot, "spot")
        if self.spot is not None and self.spot <= 0:
            raise ValueError("spot must be positive when present")
        _finite_or_none(self.spot_change, "spot_change")
        if self.window_seconds is not None and (
            not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(self.window_seconds) or self.window_seconds <= 0
        ):
            raise ValueError("window_seconds must be a finite positive number or None")
        if not isinstance(self.price_moves, tuple) or not all(
            isinstance(m, (int, float)) and math.isfinite(m) for m in self.price_moves
        ):
            raise ValueError("price_moves must be a tuple of finite numbers")
        _non_negative_or_none(self.volatility, "volatility")
        if self.positioning is not None and not isinstance(
            self.positioning, PositioningClassification
        ):
            raise ValueError("positioning must be a Day-20 PositioningClassification or None")
        if self.institutional_direction is not None and not isinstance(
            self.institutional_direction, IntelligenceDirection
        ):
            raise ValueError("institutional_direction must be an IntelligenceDirection or None")
        _range_or_none(self.institutional_strength, "institutional_strength")
        if not isinstance(self.level_classifications, tuple) or not all(
            isinstance(l, LevelClassification) for l in self.level_classifications
        ):
            raise ValueError(
                "level_classifications must be a tuple of Day-21 LevelClassification"
            )
        if not _aware(self.reference_timestamp):
            raise ValueError("reference_timestamp must be genuinely timezone-aware")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Day-9 Provenance")
        if self.quality is not None and not isinstance(self.quality, QualityResult):
            raise ValueError("quality must be a Day-12 QualityResult or None")


# ---------------------------------------------------------------------------
# Derived context layer
# ---------------------------------------------------------------------------


def _proximate_levels(inp: RegimeInput) -> tuple[LevelClassification, ...]:
    """Classified (SUPPORT/RESISTANCE) levels with a strength whose strike is
    within LEVEL_PROXIMITY_FRACTION of spot — deterministic, spot > 0."""
    if inp.spot is None or inp.spot <= 0:
        return ()
    out = []
    for lvl in inp.level_classifications:
        if lvl.kind not in (LevelKind.SUPPORT, LevelKind.RESISTANCE):
            continue
        if lvl.strength is None:
            continue
        if abs(lvl.strike - inp.spot) / inp.spot <= LEVEL_PROXIMITY_FRACTION:
            out.append(lvl)
    out.sort(key=lambda l: l.strike)
    return tuple(out)


_CONSTRUCTIVE_STATES = (
    LevelState.STATIC,
    LevelState.STRENGTHENING,
    LevelState.WEAKENING,
    LevelState.APPROACHING,
)


def _level_corroborates(levels: tuple[LevelClassification, ...], price_dir: int,
                        spot: float) -> bool:
    """Constructive proximate level consistent with the price direction:
    rising price backed by a proximate constructive SUPPORT at/below spot or
    RESISTANCE at/above spot; falling price mirrored."""
    for lvl in levels:
        if lvl.state not in _CONSTRUCTIVE_STATES:
            continue
        if lvl.kind is LevelKind.SUPPORT and lvl.strike <= spot and price_dir > 0:
            return True
        if lvl.kind is LevelKind.RESISTANCE and lvl.strike >= spot and price_dir > 0:
            return True
        if lvl.kind is LevelKind.RESISTANCE and lvl.strike >= spot and price_dir < 0:
            return True
        if lvl.kind is LevelKind.SUPPORT and lvl.strike <= spot and price_dir < 0:
            return True
    return False


def _conflicted_proximate(levels: tuple[LevelClassification, ...]) -> LevelClassification | None:
    for lvl in levels:
        if lvl.state is LevelState.CONFLICTED_INTERACTION:
            return lvl
    return None


def _window_read(moves: tuple[float, ...]) -> tuple[_PriceWindow, float | None, int]:
    """Deterministic price-window reading.

    Returns ``(reading, net_fraction, direction_sign)`` — ``net_fraction`` is
    ``|net| / gross`` over the NONZERO moves (None when gross == 0).
    """
    nonzero = [m for m in moves if m != 0.0]
    if not nonzero:
        return _PriceWindow.NONE, None, 0
    net = sum(nonzero)
    gross = sum(abs(m) for m in nonzero)
    fraction = abs(net) / gross if gross > 0 else None
    direction_sign = _sign(net)
    if len(nonzero) >= TREND_MIN_MOVES and all(
        _sign(m) == direction_sign for m in nonzero
    ):
        return _PriceWindow.TRENDING, fraction, direction_sign
    if (len(moves) >= RANGE_MIN_MOVES
            and any(m > 0 for m in moves) and any(m < 0 for m in moves)
            and fraction is not None and fraction <= RANGING_MAX_NET_FRACTION):
        return _PriceWindow.RANGING, fraction, 0
    return _PriceWindow.NONE, fraction, direction_sign


def _price_direction(inp: RegimeInput, window: _PriceWindow,
                     window_sign: int) -> int | None:
    """Usable directional price evidence: window net sign when a price window
    exists, else the single ``spot_change`` sign.  A measured flat (0.0) or
    missing price is never a directional signal."""
    if window is not _PriceWindow.NONE and window_sign != 0:
        return window_sign
    sc = inp.spot_change
    if sc is None or sc == 0.0:
        return None
    return _sign(sc)


# ---------------------------------------------------------------------------
# Evidence construction
# ---------------------------------------------------------------------------


def _issue(code: IntelligenceIssueCode, field: str | None = None,
           message: str | None = None) -> IntelligenceIssue:
    return IntelligenceIssue(code=code,
                             message=message or code.value,
                             field=field)


def _ref(inp: RegimeInput, key: str) -> str:
    scope = inp.expiry or "chain"
    return f"reg:{inp.underlying}:{scope}:{key}"


def _ev(inp: RegimeInput, key: str, value: float, unit: str | None,
        kind: EvidenceType = EvidenceType.MARKET_OBSERVATION) -> IntelligenceEvidence:
    return IntelligenceEvidence(
        source_reference_id=_ref(inp, key),
        evidence_type=kind,
        value=value,
        unit=unit,
        reference_timestamp=inp.reference_timestamp,
        provenance=inp.provenance,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )


def _evidence_rows(inp: RegimeInput, window: _PriceWindow,
                   fraction: float | None) -> list[IntelligenceEvidence]:
    """Deterministic present-value-only evidence rows."""
    out: list[IntelligenceEvidence] = []
    nonzero = [m for m in inp.price_moves if m != 0.0]
    net = sum(nonzero) if nonzero else None
    rows = [
        ("spot", inp.spot, "points"),
        ("spot_change", inp.spot_change, "points"),
        ("net_price_move", net, "points"),
        ("price_move_count", float(len(nonzero)) if nonzero else None, None),
        ("net_fraction", fraction, None),
        ("volatility", inp.volatility, "annualized_fraction"),
        ("institutional_strength", inp.institutional_strength, "score_0_1"),
    ]
    for key, value, unit in rows:
        if value is not None:
            out.append(_ev(inp, key, float(value), unit))
    for lvl in _proximate_levels(inp):
        out.append(_ev(
            inp,
            f"level_strength:{lvl.kind.value}:{lvl.strike:g}:{lvl.state.value}",
            float(lvl.strength),
            "score_0_1",
            EvidenceType.QUANT_DERIVED,
        ))
    return out


# ---------------------------------------------------------------------------
# Interpretation layer
# ---------------------------------------------------------------------------


def evaluate_regime(inp: RegimeInput) -> IntelligenceResult:
    """Evaluate one underlying and return the authoritative Day-19
    :class:`IntelligenceResult` (exactly one per evaluation, with the regime
    attached in ``result.regime``)."""
    window, fraction, window_sign = _window_read(inp.price_moves)
    issues: list[IntelligenceIssue] = []
    status: IntelligenceStatus | None = None
    direction: IntelligenceDirection | None = None
    strength: float | None = None
    confidence: float | None = None
    observation: IntelligenceObservation | None = None
    evidence: list[IntelligenceEvidence] = []
    regime_label = RegimeLabel.UNKNOWN

    def finish() -> IntelligenceResult:
        horizon = TimeHorizon.EXPIRY if status is IntelligenceStatus.SUCCESS else None
        return IntelligenceResult(
            calculation_id=CALCULATION_ID,
            status=status or IntelligenceStatus.UNAVAILABLE,
            direction=direction,
            signal_strength=strength,
            confidence=confidence,
            time_horizon=horizon,
            observation=observation,
            evidence=tuple(evidence),
            regime=MarketRegime(
                label=regime_label,
                source=CALCULATION_ID,
                model_version=MODEL_VERSION,
                reference_timestamp=inp.reference_timestamp,
            ),
            quality=inp.quality,
            provenance=inp.provenance,
            reference_timestamp=inp.reference_timestamp,
            contract_version=INTELLIGENCE_CONTRACT_VERSION,
            model_version=MODEL_VERSION,
            calculation_version=CALCULATION_VERSION,
            issues=tuple(issues),
        )

    # -- usable evidence? ---------------------------------------------------
    proximate = _proximate_levels(inp)
    has_evidence = any((
        bool(inp.price_moves),
        inp.spot is not None,
        inp.spot_change is not None,
        inp.volatility is not None,
        inp.positioning is not None,
        inp.institutional_direction is not None
        or inp.institutional_strength is not None,
        bool(proximate),
    ))
    if not has_evidence:
        issues.append(_issue(IntelligenceIssueCode.MISSING_EVIDENCE, "chain"))
        if inp.quality is None:
            issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return finish()

    evidence = _evidence_rows(inp, window, fraction)

    # -- missing quality ----------------------------------------------------
    if inp.quality is None:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.MISSING_QUALITY, "quality"))
        return finish()

    # -- insufficient quality state (Day-21 gating precedent) ---------------
    if inp.quality.quality_state is QualityState.INSUFFICIENT:
        status = IntelligenceStatus.PARTIAL
        issues.append(_issue(IntelligenceIssueCode.INSUFFICIENT_QUALITY,
                             "quality",
                             "input quality is below the interpretability floor"))
        return finish()

    price_dir = _price_direction(inp, window, window_sign)

    # -- directional sources -------------------------------------------------
    positioning_dir = classification_direction(inp.positioning) \
        if inp.positioning is not None else None

    def _agree(dir_a: IntelligenceDirection | None, price_dir: int) -> bool:
        return dir_a in (IntelligenceDirection.BULLISH, IntelligenceDirection.BEARISH) \
            and ((dir_a is IntelligenceDirection.BULLISH) == (price_dir > 0))

    def _oppose(dir_a: IntelligenceDirection | None, price_dir: int) -> bool:
        return dir_a in (IntelligenceDirection.BULLISH, IntelligenceDirection.BEARISH) \
            and ((dir_a is IntelligenceDirection.BULLISH) != (price_dir > 0))

    # -- conflicting evidence (highest priority; never hidden) ---------------
    if price_dir is not None:
        conflicted_level = _conflicted_proximate(proximate)
        opposing = (
            _oppose(positioning_dir, price_dir)
            or _oppose(inp.institutional_direction, price_dir)
            or inp.institutional_direction is IntelligenceDirection.MIXED
            or conflicted_level is not None
        )
        if opposing:
            status = IntelligenceStatus.PARTIAL
            issues.append(_issue(IntelligenceIssueCode.CONFLICTING_DIRECTION,
                                 "cross_evidence",
                                 "opposing market evidence vs price — "
                                 "conflicting regime evidence"))
            direction = IntelligenceDirection.MIXED
            if inp.institutional_strength is not None:
                strength = min(inp.institutional_strength, 1.0)
            elif conflicted_level is not None and conflicted_level.strength is not None:
                strength = conflicted_level.strength
            else:
                strength = CONFLICT_DEFAULT_STRENGTH
            confidence = CONFIDENCE_CONFLICT
            observation = IntelligenceObservation(
                metric_name="regime_strength",
                value=float(strength),
                unit="score_0_1",
            )
            return finish()

    # -- TRENDING / RANGING (price-window evidence only) ----------------------
    if window is _PriceWindow.TRENDING:
        regime_label = RegimeLabel.TRENDING
        status = IntelligenceStatus.SUCCESS
        direction = (IntelligenceDirection.BULLISH if window_sign > 0
                     else IntelligenceDirection.BEARISH)
        strength = fraction if fraction is not None else 1.0
        confidence = CONFIDENCE_TREND
        observation = IntelligenceObservation(
            metric_name="regime_strength",
            value=float(strength),
            unit="score_0_1",
        )
        return finish()

    if window is _PriceWindow.RANGING:
        regime_label = RegimeLabel.RANGING
        status = IntelligenceStatus.SUCCESS
        direction = IntelligenceDirection.NEUTRAL
        strength = 1.0 - fraction if fraction is not None else 1.0
        confidence = CONFIDENCE_RANGE
        observation = IntelligenceObservation(
            metric_name="regime_strength",
            value=float(strength),
            unit="score_0_1",
        )
        return finish()

    # -- volatility regimes (explicit measure required) ----------------------
    vol = inp.volatility
    if vol is not None:
        if vol > HIGH_VOLATILITY_THRESHOLD:
            regime_label = RegimeLabel.HIGH_VOLATILITY
            status = IntelligenceStatus.SUCCESS
            direction = IntelligenceDirection.UNKNOWN
            strength = min(vol, 1.0)
            confidence = CONFIDENCE_VOLATILITY
            observation = IntelligenceObservation(
                metric_name="regime_strength",
                value=float(strength),
                unit="score_0_1",
            )
            return finish()
        if vol < LOW_VOLATILITY_THRESHOLD:
            regime_label = RegimeLabel.LOW_VOLATILITY
            status = IntelligenceStatus.SUCCESS
            direction = IntelligenceDirection.UNKNOWN
            strength = max(0.0, 1.0 - vol / LOW_VOLATILITY_THRESHOLD)
            confidence = CONFIDENCE_VOLATILITY
            observation = IntelligenceObservation(
                metric_name="regime_strength",
                value=float(strength),
                unit="score_0_1",
            )
            return finish()

    # -- RISK_ON / RISK_OFF (price evidence + corroboration required) ---------
    if price_dir is not None:
        corroborators = 0
        if _agree(positioning_dir, price_dir):
            corroborators += 1
        if _agree(inp.institutional_direction, price_dir):
            corroborators += 1
        if _level_corroborates(proximate, price_dir, inp.spot if inp.spot is not None else 0.0):
            corroborators += 1
        if corroborators >= 1:
            regime_label = (RegimeLabel.RISK_ON if price_dir > 0
                            else RegimeLabel.RISK_OFF)
            status = IntelligenceStatus.SUCCESS
            direction = (IntelligenceDirection.BULLISH if price_dir > 0
                         else IntelligenceDirection.BEARISH)
            strength = min(corroborators / 3.0, 1.0)
            confidence = (CONFIDENCE_RISK_FULL if corroborators >= 2
                          else CONFIDENCE_RISK_MINIMAL)
            observation = IntelligenceObservation(
                metric_name="regime_strength",
                value=float(strength),
                unit="score_0_1",
            )
            return finish()

    # -- UNKNOWN (measured "cannot classify", never fabricated) ---------------
    regime_label = RegimeLabel.UNKNOWN
    status = IntelligenceStatus.SUCCESS
    direction = IntelligenceDirection.UNKNOWN
    strength = 0.0
    confidence = CONFIDENCE_UNKNOWN
    observation = IntelligenceObservation(
        metric_name="regime_strength",
        value=0.0,
        unit="score_0_1",
    )
    return finish()