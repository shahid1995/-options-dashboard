"""Quantitative Engine Boundary contracts (Day 14).

The shared backend quant domain that will become authoritative for platform
decisions (Blueprint §9 / master plan Day 14).  This module defines the
boundary's canonical contracts ONLY — no calculation engine lives here
(Greeks/IV/pricing/GEX/scenario/portfolio are Days 15-18 and must implement
the :class:`~app.quant.boundary.QuantEngine` protocol).

Architecture::

    Canonical Market Data (Day 9)     NormalizedInstrument / Provenance /
                                      QualityState / DataMode / ContractVersion
        ↓
    Data Quality (Day 12)             consumed here — NEVER recomputed
        ↓
    Quantitative Engine Boundary
        CalculationContext            deterministic environment (reference time,
                                      r, q, versions, tolerance)
        OptionMarketData              canonical calculation input
        QuantResult                   status / values / issues / quality /
                                      provenance / versions
        ↓
    Day 15+ engines → Intelligence

Design rules
------------
1. **Broker-neutral.**  This package imports only ``app.market_data``
   (canonical, broker-free) and the standard library.  Zero broker modules,
   zero broker SDKs, zero broker payload field names.
2. **Deterministic.**  Every environmental value an engine needs is supplied
   through :class:`CalculationContext`.  Engines never read the wall clock,
   the environment, the database, HTTP or broker SDKs (enforced by static
   tests).  ``reference_timestamp`` is the ONLY notion of now.
3. **No fabrication.**  Missing market values stay ``None``.  Missing
   provenance or INSUFFICIENT input quality yields a deterministic
   ``UNAVAILABLE`` result — never a guessed value.
4. **Separation of concerns.**  A result keeps calculation output, input
   quality, calculation status and provenance separate — never collapsed into
   a single confidence/score.
5. **Model vs broker semantics.**  Broker-provided Greeks/IV arrive via the
   Day-9 ``GreeksObservation(source=\"BROKER\")`` upstream; model outputs will
   be exposed with their ``calculation_id`` + versions and a model source
   label (Day 15+).  The boundary documents that mapping and does not
   duplicate it here.
6. **Versioning.**  Contract, model and calculation versions are explicit on
   every result so a future model change is traceable to the version that
   produced the result.
7. **Immutable.**  All contracts are frozen dataclasses.

Missing/invalid inputs are distinguished from unavailable calculations and
failures through :class:`CalculationStatus` + structured
:class:`QuantIssue` entries — deterministic, credential-free, broker-payload-
free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping

from app.market_data.contracts import (
    DataMode,
    NormalizedInstrument,
    Provenance,
    QualityState,
    Side,
)

# ---------------------------------------------------------------------------
# Day-count convention (input normalization policy — NOT a model)
# ---------------------------------------------------------------------------

#: ACT/365 day-count convention for option time-to-expiry normalization.
DAYS_PER_YEAR_ACT_365 = 365.0
SECONDS_PER_DAY = 86400.0
SECONDS_PER_YEAR_ACT_365 = DAYS_PER_YEAR_ACT_365 * SECONDS_PER_DAY


def time_to_expiry(expiry_date: str, reference_timestamp: datetime) -> float:
    """Deterministic ACT/365 time-to-expiry in years.

    ``expiry_date`` is ``YYYY-MM-DD`` interpreted at UTC midnight (a documented
    deterministic convention).  The result is floored at ``0.0`` once the
    expiry date has passed or is the reference date.  This is an input
    normalization utility of the boundary — it is not a model calculation.

    Raises ``ValueError`` for an unparseable expiry or a naive reference
    timestamp.
    """
    if reference_timestamp.tzinfo is None:
        raise ValueError("reference_timestamp must be timezone-aware")
    try:
        year, month, day = (int(part) for part in str(expiry_date).split("-", 2))
        expiry_midnight = datetime(year, month, day, tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"expiry_date must be an ISO YYYY-MM-DD date, got {expiry_date!r}"
        ) from exc

    remaining = (expiry_midnight - reference_timestamp.astimezone(timezone.utc)).total_seconds()
    if remaining <= 0:
        return 0.0
    return remaining / SECONDS_PER_YEAR_ACT_365


# ---------------------------------------------------------------------------
# Status / issue taxonomy (quant domain)
# ---------------------------------------------------------------------------


class CalculationStatus(str, Enum):
    """Outcome of a quantitative calculation.

    ``UNAVAILABLE`` covers "cannot be computed from what we have" (missing
    provenance, insufficient quality, unregistered calculation).  ``FAILED``
    means an engine faulted while computing.
    """

    SUCCESS = "SUCCESS"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    FAILED = "FAILED"


class CalculationIssueCode(str, Enum):
    """Structured, machine-readable quant-domain issue categories.

    These are calculation-scoped codes.  Data-quality issue codes remain the
    Day-12 quality engine's taxonomy; this boundary consumes Day-12 quality
    states and never re-scores them.
    """

    MISSING_REQUIRED_INPUT = "MISSING_REQUIRED_INPUT"
    INVALID_INPUT_VALUE = "INVALID_INPUT_VALUE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_EXPIRY = "INVALID_EXPIRY"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    INSUFFICIENT_QUALITY = "INSUFFICIENT_QUALITY"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Implied-volatility solver outcomes (Day 16) — the market price does not
    # admit a volatility solution in the documented domain, the contract is
    # expired, or the bounded root solve failed numerically.
    EXPIRED = "EXPIRED"
    BELOW_LOWER_BOUND = "BELOW_LOWER_BOUND"
    ABOVE_THEORETICAL_MAX = "ABOVE_THEORETICAL_MAX"
    NO_BRACKET = "NO_BRACKET"
    CONVERGENCE_FAILED = "CONVERGENCE_FAILED"


# ---------------------------------------------------------------------------
# Precision / tolerance policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericalTolerance:
    """Deterministic numeric precision policy for the quant boundary.

    ``nearly_equal(a, b)`` is true when the absolute difference is within
    ``absolute`` OR the relative difference is within ``relative``.
    """

    relative: float = 1e-9
    absolute: float = 1e-12

    def __post_init__(self) -> None:
        for name in ("relative", "absolute"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


def nearly_equal(
    a: float,
    b: float,
    tolerance: NumericalTolerance | None = None,
) -> bool:
    """Deterministic near-equality comparison under the tolerance policy."""
    tol = tolerance or NumericalTolerance()
    if a == b:
        return True
    diff = abs(a - b)
    if diff <= tol.absolute:
        return True
    scale = max(abs(a), abs(b))
    if scale == 0:
        return False
    return (diff / scale) <= tol.relative


# ---------------------------------------------------------------------------
# Calculation context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalculationContext:
    """The deterministic environment for every quantitative calculation.

    Engines receive ALL environmental values here — they may never read the
    wall clock, environment variables, databases, HTTP or broker SDKs.
    ``reference_timestamp`` is the only notion of "now" and is required and
    timezone-aware.
    """

    reference_timestamp: datetime
    risk_free_rate: float
    dividend_yield: float | None = None
    tolerance: NumericalTolerance = field(default_factory=NumericalTolerance)
    model_version: str | None = None
    calculation_version: str | None = None

    def __post_init__(self) -> None:
        if self.reference_timestamp.tzinfo is None:
            raise ValueError("reference_timestamp must be timezone-aware")
        if not isinstance(self.risk_free_rate, (int, float)) or not math.isfinite(
            self.risk_free_rate
        ):
            raise ValueError("risk_free_rate must be a finite number")
        if self.dividend_yield is not None and (
            not isinstance(self.dividend_yield, (int, float))
            or not math.isfinite(self.dividend_yield)
        ):
            raise ValueError("dividend_yield must be a finite number or None")


# ---------------------------------------------------------------------------
# Calculation input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionMarketData:
    """Canonical market inputs for one option calculation.

    * :attr:`instrument` — the Day-9 :class:`NormalizedInstrument` identity;
      it MUST be a concrete option contract (expiry + strike + option type).
      No broker keys/tokens appear here.
    * :attr:`spot` — underlying reference price (required, positive, finite).
    * :attr:`market_price` — observed option premium (``None`` when not
      observed; never fabricated).
    * :attr:`implied_volatility` — volatility input (``None`` when not
      supplied; e.g. Greeks engines may be given IV from upstream).
    * :attr:`quality` — the Day-12 :class:`QualityState` of the underlying
      observation, consumed as-is.  This boundary never scores quality.
    * :attr:`provenance` — Day-9 :class:`Provenance` of the input market data.
    * :attr:`gamma` — option gamma input (per-unit-per-unit) used by
      exposure calculations (Day 17 GEX).  ``None`` = missing (never
      fabricated); ``0.0`` = a legitimate zero gamma.
    * :attr:`open_interest` — open interest in **contracts** (never lots);
      ``None`` = missing, ``0.0`` = a legitimate zero.
    * :attr:`greeks_source` — explicit source label (``"BROKER"`` or
      ``"MODEL"`` per the Day-9 ``GreeksObservation`` vocabulary) for the
      gamma input; token validation is the engine's responsibility.
    * Timestamps are market/received observation times; engines must use
      ``CalculationContext.reference_timestamp`` as their notion of now.
    """

    instrument: NormalizedInstrument
    spot: float
    market_price: float | None = None
    implied_volatility: float | None = None
    market_timestamp: datetime | None = None
    received_timestamp: datetime | None = None
    data_mode: DataMode | None = None
    quality: QualityState | None = None
    provenance: Provenance | None = None
    gamma: float | None = None
    open_interest: float | None = None
    greeks_source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, NormalizedInstrument):
            raise ValueError("instrument must be a NormalizedInstrument")
        if not self.instrument.is_concrete_contract:
            raise ValueError(
                "instrument must be a concrete option contract (expiry + strike + option type)"
            )
        if self.instrument.option_type not in (Side.CALL, Side.PUT):
            raise ValueError("instrument.option_type must be CALL or PUT")
        if self.instrument.strike is None or not math.isfinite(self.instrument.strike):
            raise ValueError("instrument.strike must be a finite number")
        if self.instrument.strike <= 0:
            raise ValueError("instrument.strike must be positive")
        if not isinstance(self.spot, (int, float)) or not math.isfinite(self.spot):
            raise ValueError("spot must be a finite number")
        if self.spot <= 0:
            raise ValueError("spot must be positive")
        for name in ("market_price", "implied_volatility", "gamma", "open_interest"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{name} must be a finite number or None")
                if value < 0:
                    raise ValueError(f"{name} must be non-negative")
        for name in ("market_timestamp", "received_timestamp"):
            value = getattr(self, name)
            if value is not None and getattr(value, "tzinfo", None) is None:
                raise ValueError(f"{name} must be timezone-aware when present")
        try:
            datetime.strptime(self.instrument.expiry, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"instrument.expiry must be an ISO YYYY-MM-DD date, got {self.instrument.expiry!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Issues / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantIssue:
    """A structured, machine-readable quant-domain issue.

    ``message`` is a safe static string — never a broker payload, credential,
    or exception text.
    """

    code: CalculationIssueCode
    message: str
    field: str | None = None

    def __repr__(self) -> str:
        return (
            f"QuantIssue(code={self.code.value!r}, field={self.field!r}, "
            f"message={self.message!r})"
        )


@dataclass(frozen=True)
class QuantResult:
    """The reusable quantitative-result envelope.

    Keeps the four concepts separate:
    * ``values`` — what the mathematical model calculated (None unless SUCCESS)
    * ``input_quality`` — whether the underlying market inputs were trustworthy
    * ``status`` — whether the calculation succeeded / was unavailable /
      invalid / failed
    * ``provenance`` + versions — where the inputs came from and exactly which
      implementation produced the result

    These are never collapsed into a single confidence/score.

    ``greeks_source`` records which gamma/IV inputs the calculation consumed
    (``"BROKER"``/``"MODEL"``) when the engine is required to identify them
    (Day 17 GEX); it stays ``None`` for calculations that do not consume
    greeks inputs.  Never fabricated.
    """

    calculation_id: str
    status: CalculationStatus
    values: Mapping[str, float] | None = None
    issues: tuple[QuantIssue, ...] = ()
    input_quality: QualityState | None = None
    provenance: Provenance | None = None
    reference_timestamp: datetime | None = None
    model_version: str | None = None
    calculation_version: str | None = None
    contract_version: str | None = None
    greeks_source: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is CalculationStatus.SUCCESS
