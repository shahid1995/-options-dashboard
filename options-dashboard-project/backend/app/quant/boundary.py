"""Quantitative Engine Boundary (Day 14) — routing, guards and the engine
protocol.

The boundary is the deterministic entry point for every quantitative
calculation.  It owns:

* the :class:`QuantEngine` protocol that Day 15+ engines implement;
* registry-lite routing (register / run / available);
* boundary guards: canonical input types, mandatory provenance, the Day-12
  quality gate, and post-run envelope integrity;
* provenance / quality / version propagation into :class:`QuantResult`.

The boundary NEVER computes a market value itself and never reads hidden
environmental state — calculations run only on explicit
:class:`~app.quant.contracts.OptionMarketData` + :class:`~app.quant.contracts.CalculationContext`
inputs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from app.market_data.contracts import QualityState
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    OptionMarketData,
    QuantIssue,
    QuantResult,
)

#: Quality policy (documented + tested): EXCELLENT/GOOD are always permitted;
#: DEGRADED is permitted but the degraded state is preserved on the result;
#: INSUFFICIENT means the required inputs are unreliable → the calculation is
#: UNAVAILABLE.  A missing quality state (None) is distinct from INSUFFICIENT —
#: the boundary never scores quality itself (Day 12 is authoritative).
_BLOCKING_QUALITY = frozenset({QualityState.INSUFFICIENT})

# Default safety messages (static, credential-free, broker-payload-free).
_MSG_MISSING_PROVENANCE = (
    "Input market data carries no provenance — the calculation cannot answer "
    "where/when/how its inputs were produced and is unavailable."
)
_MSG_INSUFFICIENT_QUALITY = (
    "Input market data quality is INSUFFICIENT; required inputs are unreliable "
    "so the calculation is unavailable under the boundary quality policy."
)
_MSG_NOT_IMPLEMENTED = (
    "No engine is registered for this calculation id — nothing is fabricated."
)
_MSG_ENGINE_FAULT = (
    "The calculation engine raised an internal error while computing."
)
_MSG_NON_RESULT = "The engine did not return a QuantResult."
_MSG_SUCCESS_WITHOUT_VALUES = (
    "The engine reported SUCCESS without output values — a successful "
    "calculation must carry its computed values."
)


class QuantEngine(Protocol):
    """Protocol every Day 15+ quantitative engine implements.

    ``calculation_id`` is the canonical, version-independent identifier
    (e.g. ``greeks.black_scholes_european``).  ``calculate`` must be a pure
    function of its inputs: same ``OptionMarketData`` + ``CalculationContext``
    ⇒ same ``QuantResult``.  Engines never read the wall clock, DB, HTTP or
    broker SDKs.
    """

    calculation_id: str

    def calculate(
        self,
        market_data: OptionMarketData,
        context: CalculationContext,
    ) -> QuantResult: ...


class QuantitativeEngineBoundary:
    """Deterministic routing + guard boundary for quantitative engines."""

    def __init__(self) -> None:
        self._engines: dict[str, QuantEngine] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, engine: QuantEngine) -> None:
        """Register an engine under its ``calculation_id`` (no duplicates)."""
        calculation_id = getattr(engine, "calculation_id", None)
        if not isinstance(calculation_id, str) or not calculation_id:
            raise ValueError("Engine must expose a non-empty calculation_id")
        if not callable(getattr(engine, "calculate", None)):
            raise ValueError("Engine must implement calculate(market_data, context)")
        if calculation_id in self._engines:
            raise ValueError(f"An engine is already registered for {calculation_id!r}")
        self._engines[calculation_id] = engine

    def available_calculations(self) -> tuple[str, ...]:
        """Registered calculation ids, sorted for determinism."""
        return tuple(sorted(self._engines))

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        calculation_id: str,
        market_data: OptionMarketData,
        context: CalculationContext,
    ) -> QuantResult:
        """Run one calculation through the boundary.

        Guards run BEFORE the engine: missing provenance or INSUFFICIENT input
        quality yields a deterministic UNAVAILABLE result (the engine is never
        invoked).  An unregistered calculation yields UNAVAILABLE /
        NOT_IMPLEMENTED — never a fabricated value.  Engine faults become
        FAILED / INTERNAL_ERROR results; the exception text never leaks.
        """
        if not isinstance(market_data, OptionMarketData):
            raise TypeError("market_data must be an OptionMarketData")
        if not isinstance(context, CalculationContext):
            raise TypeError("context must be a CalculationContext")

        # Provenance guard — never replace missing provenance with a fabricated
        # "unknown" that would falsely imply a valid source.
        if market_data.provenance is None:
            return self._unavailable(
                calculation_id=calculation_id,
                market_data=market_data,
                context=context,
                issue=QuantIssue(
                    code=CalculationIssueCode.MISSING_PROVENANCE,
                    message=_MSG_MISSING_PROVENANCE,
                    field="provenance",
                ),
            )

        # Day-12 quality gate — quality is consumed, never recomputed.
        if market_data.quality in _BLOCKING_QUALITY:
            return self._unavailable(
                calculation_id=calculation_id,
                market_data=market_data,
                context=context,
                issue=QuantIssue(
                    code=CalculationIssueCode.INSUFFICIENT_QUALITY,
                    message=_MSG_INSUFFICIENT_QUALITY,
                    field="quality",
                ),
            )

        engine = self._engines.get(calculation_id)
        if engine is None:
            return self._unavailable(
                calculation_id=calculation_id,
                market_data=market_data,
                context=context,
                issue=QuantIssue(
                    code=CalculationIssueCode.NOT_IMPLEMENTED,
                    message=_MSG_NOT_IMPLEMENTED,
                    field="calculation_id",
                ),
            )

        try:
            result = engine.calculate(market_data, context)
        except Exception:  # noqa: BLE001 — engine faults become structured results
            return self._failed(
                calculation_id=calculation_id,
                market_data=market_data,
                context=context,
                issue=QuantIssue(
                    code=CalculationIssueCode.INTERNAL_ERROR,
                    message=_MSG_ENGINE_FAULT,
                ),
            )

        if not isinstance(result, QuantResult):
            return self._failed(
                calculation_id=calculation_id,
                market_data=market_data,
                context=context,
                issue=QuantIssue(
                    code=CalculationIssueCode.INTERNAL_ERROR,
                    message=_MSG_NON_RESULT,
                ),
            )
        if result.status is CalculationStatus.SUCCESS and result.values is None:
            return self._failed(
                calculation_id=calculation_id,
                market_data=market_data,
                context=context,
                issue=QuantIssue(
                    code=CalculationIssueCode.INTERNAL_ERROR,
                    message=_MSG_SUCCESS_WITHOUT_VALUES,
                ),
            )

        # Envelope integrity: propagate provenance / quality / versions when
        # the engine omitted them — the boundary is responsible for them.
        return replace(
            result,
            calculation_id=calculation_id,
            provenance=result.provenance if result.provenance is not None else market_data.provenance,
            input_quality=result.input_quality if result.input_quality is not None else market_data.quality,
            reference_timestamp=(
                result.reference_timestamp
                if result.reference_timestamp is not None
                else context.reference_timestamp
            ),
            model_version=result.model_version or context.model_version,
            calculation_version=result.calculation_version or context.calculation_version,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _unavailable(
        self,
        *,
        calculation_id: str,
        market_data: OptionMarketData,
        context: CalculationContext,
        issue: QuantIssue,
    ) -> QuantResult:
        return QuantResult(
            calculation_id=calculation_id,
            status=CalculationStatus.UNAVAILABLE,
            values=None,
            issues=(issue,),
            input_quality=market_data.quality,
            provenance=market_data.provenance,
            reference_timestamp=context.reference_timestamp,
            model_version=context.model_version,
            calculation_version=context.calculation_version,
        )

    def _failed(
        self,
        *,
        calculation_id: str,
        market_data: OptionMarketData,
        context: CalculationContext,
        issue: QuantIssue,
    ) -> QuantResult:
        return QuantResult(
            calculation_id=calculation_id,
            status=CalculationStatus.FAILED,
            values=None,
            issues=(issue,),
            input_quality=market_data.quality,
            provenance=market_data.provenance,
            reference_timestamp=context.reference_timestamp,
            model_version=context.model_version,
            calculation_version=context.calculation_version,
        )
