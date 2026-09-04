"""Day 35 — Portfolio analytics engine (pure, deterministic).

``analyze_portfolio`` consumes normalized authoritative ``PortfolioPosition``
inputs (plus an optional Day-23 regime and supplied Day-18 scenario rows) and
returns the full ``PortfolioAnalyticsResult``.

Every analytical rule is deterministic and evidence-backed:

* Exposure/Greek totals scale per-unit evidence by the explicit signed
  quantity (direction.sign x quantity) — the same convention the Day-18
  scenario engine uses.  Missing evidence stays missing: totals sum only
  present values and the view state (AVAILABLE/PARTIAL/UNAVAILABLE) reports
  incomplete coverage.
* Portfolio-owned GEX reuses ``app.quant.gex.raw_gex`` on the portfolio's own
  gamma x own contract count x spot, signed by direction — never the
  market/dealer GEX and never a second GEX formula.
* Concentration is measurement over absolute normalized quantity with no
  danger/verdict vocabulary.
* The directional view reads net delta only; a Day-23 regime label never
  manufactures direction (that rule is enforced in the regime view, which
  restates delta only when delta evidence exists).
* Tenants never mix: a cross-tenant input produces a deterministic INVALID
  result with zero cross-tenant aggregation.

This module performs no I/O of any kind: positions, regime, scenario rows and
the reference timestamp are all caller-supplied.
"""

from __future__ import annotations

from app.intelligence.contracts import MarketRegime, RegimeLabel
from app.market_data.contracts import Provenance, QualityState
from app.quant.gex import raw_gex

from app.portfolio_intelligence.contracts import (
    CALCULATION_VERSION,
    CONTRACT_VERSION,
    GEX_METHOD_VERSION,
    MODEL_VERSION,
    ConcentrationSlice,
    ConcentrationView,
    DeltaPosture,
    DirectionalView,
    EvidenceState,
    ExposureSlice,
    GexSourceTotal,
    GreekContribution,
    GreekSourceTotal,
    LargestAbsoluteExposure,
    PortfolioAnalyticsResult,
    PortfolioExposure,
    PortfolioGexExposure,
    PortfolioGreekExposure,
    PortfolioIssue,
    PortfolioIssueCode,
    PortfolioPosition,
    PortfolioScenarioSensitivity,
    PortfolioStatus,
    RegimeRiskView,
    ScenarioRow,
)

#: Deterministic ordering of quality states (worst last).  The merged quality
#: channel picks the worst PRESENT state — it never invents a state when all
#: are missing.
_QUALITY_RANK = {
    QualityState.EXCELLENT: 0,
    QualityState.GOOD: 1,
    QualityState.DEGRADED: 2,
    QualityState.INSUFFICIENT: 3,
}

_GREEK_NAMES = ("delta", "gamma", "theta", "vega", "rho")


def _empty_exposure_views(positions: tuple[PortfolioPosition, ...]) -> tuple:
    """View skeletons used when analytics must not run (cross-tenant INVALID)."""
    empty_issue = ()
    empty_exposure = PortfolioExposure(
        state=EvidenceState.UNAVAILABLE,
        position_count=0,
        signed_quantity_total=0.0,
        long_quantity_total=0.0,
        short_quantity_total=0.0,
        quantity_unit="authoritative position unit",
        market_value_total=None,
        market_value_positions=0,
        positions_missing_market_value=(),
        by_expiry=(),
        by_option_type=(),
        by_direction=(),
    )
    empty_greeks = PortfolioGreekExposure(
        state=EvidenceState.UNAVAILABLE,
        by_source=(),
        sources=(),
        contributions=(),
        missing_positions=tuple(p.position_id for p in positions),
    )
    empty_gex = PortfolioGexExposure(
        state=EvidenceState.UNAVAILABLE,
        methodology=GEX_METHOD_VERSION,
        by_source=(),
    )
    empty_scenarios = PortfolioScenarioSensitivity(
        state=EvidenceState.UNAVAILABLE,
        rows=(),
        point_count=0,
        complete_rows=0,
        partial_rows=0,
        worst_supplied_pnl=None,
        worst_supplied_point_id=None,
        best_supplied_pnl=None,
    )
    empty_concentration = ConcentrationView(
        state=EvidenceState.UNAVAILABLE,
        basis="absolute normalized quantity",
        by_strike=(),
        by_expiry=(),
        by_option_type=(),
    )
    empty_directional = DirectionalView(
        state=EvidenceState.UNAVAILABLE,
        net_delta=None,
        delta_posture=DeltaPosture.NO_DELTA_EVIDENCE,
        call_delta=None,
        put_delta=None,
        long_delta=None,
        short_delta=None,
        positions_with_delta=0,
        positions_total=len(positions),
        missing_delta_positions=tuple(p.position_id for p in positions),
    )
    empty_regime = RegimeRiskView(
        state=EvidenceState.UNAVAILABLE,
        regime=None,
        regime_label=None,
        net_delta_context=None,
        delta_posture_context=DeltaPosture.NO_DELTA_EVIDENCE,
        notes=("Analytics did not run: cross-tenant input rejected.",),
    )
    return (empty_exposure, empty_greeks, empty_gex, empty_scenarios,
            empty_concentration, empty_directional, empty_regime)


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------


def _exposure_view(positions: tuple[PortfolioPosition, ...]) -> PortfolioExposure:
    issues: list[PortfolioIssue] = []
    signed_total = sum(p.signed_quantity for p in positions)
    long_total = sum(p.quantity for p in positions
                     if p.direction.value == "LONG")
    short_total = sum(p.quantity for p in positions
                      if p.direction.value == "SHORT")

    valued = [p for p in positions if p.market_value is not None]
    missing_value = tuple(p.position_id for p in positions
                          if p.market_value is None)

    def _slice_by(key_fn) -> tuple[ExposureSlice, ...]:
        groups: dict[str, list[PortfolioPosition]] = {}
        for p in positions:
            groups.setdefault(key_fn(p), []).append(p)
        out = []
        for key, members in sorted(groups.items()):
            out.append(
                ExposureSlice(
                    key=key,
                    signed_quantity=sum(m.signed_quantity for m in members),
                    absolute_quantity=sum(m.quantity for m in members),
                    position_count=len(members),
                )
            )
        return tuple(out)

    state = EvidenceState.AVAILABLE
    market_total = round(sum(float(p.market_value) for p in valued), 10) \
        if valued else None
    if missing_value:
        issues.append(
            PortfolioIssue(
                code=PortfolioIssueCode.PARTIAL_EVIDENCE,
                message="Market value is unavailable for some positions; the "
                        "market-value total covers only observed values and a "
                        "missing value never contributes zero.",
                field="market_value",
            )
        )
    return PortfolioExposure(
        state=state,
        position_count=len(positions),
        signed_quantity_total=round(signed_total, 10),
        long_quantity_total=round(long_total, 10),
        short_quantity_total=round(short_total, 10),
        quantity_unit="authoritative position unit "
                      "(paper: lots; broker: broker contracts)",
        market_value_total=market_total,
        market_value_positions=len(valued),
        positions_missing_market_value=missing_value,
        by_expiry=_slice_by(lambda p: p.expiry),
        by_option_type=_slice_by(lambda p: p.option_type.value),
        by_direction=_slice_by(lambda p: p.direction.value),
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------


def _greek_view(positions: tuple[PortfolioPosition, ...]) -> PortfolioGreekExposure:
    present = [p for p in positions if p.greeks is not None]
    issues: list[PortfolioIssue] = []
    if not present:
        return PortfolioGreekExposure(
            state=EvidenceState.UNAVAILABLE,
            by_source=(),
            sources=(),
            contributions=(),
            missing_positions=tuple(p.position_id for p in positions),
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.MISSING_GREEKS,
                message="No position supplies Greek evidence; aggregate "
                        "Greeks are unavailable (missing is never zero).",
                field="greeks",
            ),),
        )

    contributions: list[GreekContribution] = []
    for p in present:
        contributions.append(
            GreekContribution(
                position_id=p.position_id,
                greeks_source=p.greeks.source,
                delta=(p.greeks.delta * p.signed_quantity
                       if p.greeks.delta is not None else None),
                gamma=(p.greeks.gamma * p.signed_quantity
                       if p.greeks.gamma is not None else None),
                theta=(p.greeks.theta * p.signed_quantity
                       if p.greeks.theta is not None else None),
                vega=(p.greeks.vega * p.signed_quantity
                      if p.greeks.vega is not None else None),
                rho=(p.greeks.rho * p.signed_quantity
                     if p.greeks.rho is not None else None),
                quality=p.greeks.quality,
                provenance=p.greeks.provenance,
            )
        )

    def _scaled(p: PortfolioPosition, name: str) -> float | None:
        value = getattr(p.greeks, name)
        return (value * p.signed_quantity
                if value is not None else None)

    # Source-separated totals: broker and model evidence NEVER mix in one
    # number (same architectural principle as the portfolio GEX view).  One
    # ``GreekSourceTotal`` per contributing source, in deterministic sorted
    # source order.
    sources = tuple(sorted({p.greeks.source for p in present}))
    per_source: list[GreekSourceTotal] = []
    overall_unavailable = False
    overall_partial = False
    for source in sources:
        members = [p for p in present if p.greeks.source == source]
        supplied: dict[str, list[float]] = {name: [] for name in _GREEK_NAMES}
        contributing_ids: list[str] = []
        missing_ids: list[str] = []
        for p in members:
            per_position = [
                name for name in _GREEK_NAMES
                if _scaled(p, name) is not None
            ]
            if not per_position:
                missing_ids.append(p.position_id)
                continue
            contributing_ids.append(p.position_id)
            for name in per_position:
                supplied[name].append(float(_scaled(p, name)))  # type: ignore[arg-type]
            for name in _GREEK_NAMES:
                if name not in per_position:
                    missing_ids.append(p.position_id)
        totals = {
            name: (round(sum(vals), 10) if vals else None)
            for name, vals in supplied.items()
        }
        if not contributing_ids:
            source_state = EvidenceState.UNAVAILABLE
        elif missing_ids:
            source_state = EvidenceState.PARTIAL
        else:
            source_state = EvidenceState.AVAILABLE
        per_source.append(GreekSourceTotal(
            source=source,
            delta_total=totals["delta"],
            gamma_total=totals["gamma"],
            theta_total=totals["theta"],
            vega_total=totals["vega"],
            rho_total=totals["rho"],
            contributing_positions=tuple(contributing_ids),
            missing_positions=tuple(dict.fromkeys(missing_ids)),
            state=source_state,
        ))
        if source_state is EvidenceState.UNAVAILABLE:
            overall_unavailable = True
        elif source_state is EvidenceState.PARTIAL:
            overall_partial = True

    missing_positions = tuple(
        p.position_id for p in present
        if any(getattr(p.greeks, name) is None for name in _GREEK_NAMES)
    )

    if overall_partial:
        state = EvidenceState.PARTIAL
        issues.append(PortfolioIssue(
            code=PortfolioIssueCode.PARTIAL_EVIDENCE,
            message="Some positions lack one or more per-unit Greeks; each "
                    "source total covers only supplied values and missing "
                    "Greeks never contribute zero.",
            field="greeks",
        ))
    elif overall_unavailable and not any(
        entry.state is EvidenceState.AVAILABLE for entry in per_source
    ):
        state = EvidenceState.UNAVAILABLE
    else:
        state = EvidenceState.AVAILABLE

    return PortfolioGreekExposure(
        state=state,
        by_source=tuple(per_source),
        sources=sources,
        contributions=tuple(contributions),
        missing_positions=missing_positions,
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# Portfolio-owned GEX
# ---------------------------------------------------------------------------


def _own_contracts(position: PortfolioPosition) -> float:
    """Portfolio-owned contract count for one position.

    Multiplier is applied ONLY when the authoritative lot size is supplied;
    otherwise the normalized quantity itself is the contract count (both
    conventions are documented on the position input).  Nothing is invented.
    """
    if position.lot_size is not None:
        return position.quantity * position.lot_size
    return position.quantity


def _gex_view(positions: tuple[PortfolioPosition, ...]) -> PortfolioGexExposure:
    issues: list[PortfolioIssue] = []
    sources = sorted({p.greeks.source for p in positions
                      if p.greeks is not None})

    if not sources:
        return PortfolioGexExposure(
            state=EvidenceState.UNAVAILABLE,
            methodology=GEX_METHOD_VERSION,
            by_source=(),
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.MISSING_GEX_INPUT,
                message="No position supplies Greek evidence; portfolio-owned "
                        "GEX is unavailable (missing is never zero).",
                field="greeks",
            ),),
        )

    per_source: list[GexSourceTotal] = []
    overall_missing = False
    overall_partial = False
    for source in sources:
        members = [p for p in positions
                   if p.greeks is not None and p.greeks.source == source]
        contributing: list[float] = []
        contributing_ids: list[str] = []
        missing_ids: list[str] = []
        for p in members:
            if p.greeks.gamma is None:
                missing_ids.append(p.position_id)
                continue
            if p.spot is None:
                missing_ids.append(p.position_id)
                continue
            try:
                # The portfolio's own contract count already includes the
                # position quantity (raw_gex consumes TOTAL owned contracts as
                # its "open interest" argument); only the explicit direction
                # sign is applied on top.
                raw = raw_gex(float(p.greeks.gamma), _own_contracts(p),
                              float(p.spot))
            except ValueError:
                missing_ids.append(p.position_id)
                continue
            contributing.append(p.direction.sign * raw)
            contributing_ids.append(p.position_id)
        if not contributing_ids:
            state = EvidenceState.UNAVAILABLE
            total = None
        elif missing_ids:
            state = EvidenceState.PARTIAL
            total = round(sum(contributing), 10)
        else:
            state = EvidenceState.AVAILABLE
            total = round(sum(contributing), 10)
        per_source.append(GexSourceTotal(
            source=source,
            signed_gex_total=total,
            contributing_positions=tuple(contributing_ids),
            missing_positions=tuple(missing_ids),
            state=state,
        ))
        if state is EvidenceState.UNAVAILABLE:
            overall_missing = True
        elif state is EvidenceState.PARTIAL:
            overall_partial = True

    if overall_missing and not overall_partial and not any(
        s.state is EvidenceState.AVAILABLE for s in per_source
    ):
        overall_state = EvidenceState.UNAVAILABLE
    elif overall_partial or any(s.state is EvidenceState.PARTIAL
                                for s in per_source):
        overall_state = EvidenceState.PARTIAL
        issues.append(PortfolioIssue(
            code=PortfolioIssueCode.MISSING_GEX_INPUT,
            message="Some positions lack the gamma or spot required for "
                    "portfolio-owned GEX; totals cover only complete "
                    "positions (missing never contributes zero).",
            field="gex",
        ))
    else:
        overall_state = EvidenceState.AVAILABLE

    return PortfolioGexExposure(
        state=overall_state,
        methodology=GEX_METHOD_VERSION,
        by_source=tuple(per_source),
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# Scenario sensitivity (aggregation of supplied Day-18 rows)
# ---------------------------------------------------------------------------


def _scenario_view(rows: tuple[ScenarioRow, ...]) -> PortfolioScenarioSensitivity:
    if not rows:
        return PortfolioScenarioSensitivity(
            state=EvidenceState.UNAVAILABLE,
            rows=(),
            point_count=0,
            complete_rows=0,
            partial_rows=0,
            worst_supplied_pnl=None,
            worst_supplied_point_id=None,
            best_supplied_pnl=None,
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.MISSING_SCENARIO,
                message="No scenario rows were supplied; scenario sensitivity "
                        "is unavailable (missing is never zero).",
                field="scenarios",
            ),),
        )

    complete = [r for r in rows if not r.partial and r.total_pnl is not None]
    partial_rows = sum(1 for r in rows if r.partial or r.total_pnl is None)
    issues: list[PortfolioIssue] = []
    state = EvidenceState.AVAILABLE if len(complete) == len(rows) \
        else EvidenceState.PARTIAL
    if partial_rows:
        issues.append(PortfolioIssue(
            code=PortfolioIssueCode.PARTIAL_EVIDENCE,
            message="Some scenario rows are incomplete; P/L aggregates cover "
                    "only fully priced rows and a partial row never "
                    "contributes zero P/L.",
            field="scenarios",
        ))

    if not complete:
        return PortfolioScenarioSensitivity(
            state=EvidenceState.UNAVAILABLE,
            rows=rows,
            point_count=len(rows),
            complete_rows=len(complete),
            partial_rows=partial_rows,
            worst_supplied_pnl=None,
            worst_supplied_point_id=None,
            best_supplied_pnl=None,
            issues=tuple(issues),
        )

    worst = min(complete, key=lambda r: (r.total_pnl, r.point_id))
    best = max(complete, key=lambda r: (r.total_pnl, r.point_id))
    return PortfolioScenarioSensitivity(
        state=state,
        rows=rows,
        point_count=len(rows),
        complete_rows=len(complete),
        partial_rows=partial_rows,
        worst_supplied_pnl=worst.total_pnl,
        worst_supplied_point_id=worst.point_id,
        best_supplied_pnl=best.total_pnl,
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# Concentration (measurement only)
# ---------------------------------------------------------------------------


def _concentration_view(
    positions: tuple[PortfolioPosition, ...],
) -> ConcentrationView:
    if not positions:
        return ConcentrationView(
            state=EvidenceState.UNAVAILABLE,
            basis="absolute normalized quantity",
            by_strike=(),
            by_expiry=(),
            by_option_type=(),
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.EMPTY_PORTFOLIO,
                message="No positions to measure; concentration is "
                        "unavailable.",
                field="concentration",
            ),),
        )

    total = sum(p.quantity for p in positions)

    def _slices(key_fn) -> tuple[ConcentrationSlice, ...]:
        groups: dict[str, list[PortfolioPosition]] = {}
        for p in positions:
            groups.setdefault(key_fn(p), []).append(p)
        slices = []
        for key, members in groups.items():
            exposure = sum(m.quantity for m in members)
            slices.append(ConcentrationSlice(
                key=key,
                exposure=round(exposure, 10),
                share=round(exposure / total, 10) if total else 0.0,
                position_count=len(members),
            ))
        # deterministic: descending share, then ascending key
        return tuple(sorted(slices, key=lambda s: (-s.share, s.key)))

    largest = sorted(positions, key=lambda p: (-p.quantity, p.position_id))[0]
    return ConcentrationView(
        state=EvidenceState.AVAILABLE,
        basis="absolute normalized quantity "
              "(same authoritative unit as the exposure view)",
        by_strike=_slices(lambda p: repr(float(p.strike))),
        by_expiry=_slices(lambda p: p.expiry),
        by_option_type=_slices(lambda p: p.option_type.value),
        largest_absolute=LargestAbsoluteExposure(
            position_id=largest.position_id,
            absolute_exposure=round(largest.quantity, 10),
        ),
    )


# ---------------------------------------------------------------------------
# Directional view (delta evidence only)
# ---------------------------------------------------------------------------


def _directional_view(
    positions: tuple[PortfolioPosition, ...],
) -> DirectionalView:
    issues: list[PortfolioIssue] = []
    with_delta = [p for p in positions
                  if p.greeks is not None and p.greeks.delta is not None]
    missing = tuple(p.position_id for p in positions
                    if p.greeks is None or p.greeks.delta is None)

    if not with_delta:
        return DirectionalView(
            state=EvidenceState.UNAVAILABLE,
            net_delta=None,
            delta_posture=DeltaPosture.NO_DELTA_EVIDENCE,
            call_delta=None,
            put_delta=None,
            long_delta=None,
            short_delta=None,
            positions_with_delta=0,
            positions_total=len(positions),
            missing_delta_positions=missing,
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.NO_DIRECTIONAL_EVIDENCE,
                message="No position supplies a delta; directional exposure "
                        "is unavailable and nothing is guessed from labels.",
                field="delta",
            ),),
        )

    def _sum(filter_fn):
        values = [p.greeks.delta * p.signed_quantity for p in with_delta
                  if filter_fn(p)]
        return round(sum(values), 10) if values else None

    net = round(sum(p.greeks.delta * p.signed_quantity for p in with_delta), 10)
    state = EvidenceState.AVAILABLE if not missing \
        else EvidenceState.PARTIAL
    if missing:
        issues.append(PortfolioIssue(
            code=PortfolioIssueCode.PARTIAL_EVIDENCE,
            message="Some positions lack a delta; the net delta covers only "
                    "supplied values and a missing delta never contributes "
                    "zero.",
            field="delta",
        ))

    if net > 0:
        posture = DeltaPosture.LONG_DELTA
    elif net < 0:
        posture = DeltaPosture.SHORT_DELTA
    else:
        posture = DeltaPosture.DELTA_NEUTRAL

    return DirectionalView(
        state=state,
        net_delta=net,
        delta_posture=posture,
        call_delta=_sum(lambda p: p.option_type.value == "CALL"),
        put_delta=_sum(lambda p: p.option_type.value == "PUT"),
        long_delta=_sum(lambda p: p.direction.value == "LONG"),
        short_delta=_sum(lambda p: p.direction.value == "SHORT"),
        positions_with_delta=len(with_delta),
        positions_total=len(positions),
        missing_delta_positions=missing,
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# Regime-aware risk view (contextual only)
# ---------------------------------------------------------------------------


def _regime_view(
    regime: MarketRegime | None,
    directional: DirectionalView,
    positions_total: int,
) -> RegimeRiskView:
    if regime is None:
        return RegimeRiskView(
            state=EvidenceState.UNAVAILABLE,
            regime=None,
            regime_label=None,
            net_delta_context=None,
            delta_posture_context=DeltaPosture.NO_DELTA_EVIDENCE,
            notes=("No Day-23 market regime was supplied; regime context is "
                   "unknown and nothing is assumed.",),
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.MISSING_REGIME,
                message="No regime input was supplied.",
                field="regime",
            ),),
        )
    if regime.label is RegimeLabel.UNKNOWN:
        return RegimeRiskView(
            state=EvidenceState.UNAVAILABLE,
            regime=regime,
            regime_label=regime.label,
            net_delta_context=None,
            delta_posture_context=DeltaPosture.NO_DELTA_EVIDENCE,
            notes=("The Day-23 regime label is UNKNOWN; the regime stays "
                   "unknown and no directional evidence is fabricated.",),
            issues=(PortfolioIssue(
                code=PortfolioIssueCode.REGIME_UNKNOWN,
                message="Regime label is UNKNOWN; nothing is guessed.",
                field="regime",
            ),),
        )

    # A known label is contextual only.  Directional context is restated
    # EXCLUSIVELY from the portfolio's measured delta evidence.
    if directional.net_delta is not None:
        state = EvidenceState.AVAILABLE
        notes = (
            f"The Day-23 regime label {regime.label.value} is contextual "
            "evidence only; it implies no direction for this portfolio. "
            "Measured net delta exposure is "
            f"{directional.net_delta:g} ({directional.delta_posture.value}).",
        )
    else:
        state = EvidenceState.PARTIAL
        notes = (
            f"The Day-23 regime label {regime.label.value} is contextual "
            "evidence only; portfolio directional evidence is incomplete, so "
            "no directional statement is made.",
        )
    return RegimeRiskView(
        state=state,
        regime=regime,
        regime_label=regime.label,
        net_delta_context=directional.net_delta,
        delta_posture_context=directional.delta_posture,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def analyze_portfolio(
    positions,
    *,
    regime: MarketRegime | None = None,
    scenario_rows=(),
    reference_timestamp,
    analysis_provenance: Provenance | None = None,
) -> PortfolioAnalyticsResult:
    """Deterministic portfolio analytics over authoritative position inputs.

    ``positions`` — an iterable of genuine :class:`PortfolioPosition` objects
    (from the normalization adapters or the caller's adapter).
    ``regime`` — optional authoritative Day-23 ``MarketRegime``.
    ``scenario_rows`` — optional supplied Day-18 scenario rows.
    ``reference_timestamp`` — required, caller-supplied, timezone-aware (the
    ONLY notion of now; never read from the wall clock).
    ``analysis_provenance`` — optional canonical provenance for the analysis
    call itself (preserved verbatim on the result).

    Cross-tenant inputs produce a deterministic INVALID result with no
    cross-tenant aggregation.
    """
    if reference_timestamp is None:
        raise TypeError("reference_timestamp is required (caller-supplied)")
    if reference_timestamp.tzinfo is None or \
            reference_timestamp.tzinfo.utcoffset(reference_timestamp) is None:
        raise ValueError("reference_timestamp must be genuinely timezone-aware")
    if regime is not None and not isinstance(regime, MarketRegime):
        raise ValueError("regime must be a MarketRegime or None")
    if analysis_provenance is not None and \
            not isinstance(analysis_provenance, Provenance):
        raise ValueError("analysis_provenance must be a Provenance or None")

    normalized = tuple(positions)
    for p in normalized:
        if not isinstance(p, PortfolioPosition):
            raise TypeError("every position must be a PortfolioPosition")

    rows = tuple(scenario_rows)
    for r in rows:
        if not isinstance(r, ScenarioRow):
            raise TypeError("every scenario row must be a ScenarioRow")

    tenant_ids = {p.tenant_id for p in normalized}
    issues: list[PortfolioIssue] = []

    # Tenant isolation: portfolio calculations for one tenant must never
    # consume another tenant's positions (or scenario rows).
    if len(tenant_ids) > 1:
        return _invalid_result(
            normalized, rows, reference_timestamp, analysis_provenance,
            PortfolioIssue(
                code=PortfolioIssueCode.MIXED_TENANT,
                message="Positions from multiple tenants were supplied; "
                        "cross-tenant aggregation is never performed.",
                field="tenant_id",
            ),
        )
    if normalized and rows and any(r.tenant_id != normalized[0].tenant_id
                                   for r in rows):
        return _invalid_result(
            normalized, rows, reference_timestamp, analysis_provenance,
            PortfolioIssue(
                code=PortfolioIssueCode.MIXED_TENANT,
                message="Scenario rows belong to a different tenant than the "
                        "positions; cross-tenant aggregation is never "
                        "performed.",
                field="tenant_id",
            ),
        )

    exposure = _exposure_view(normalized)
    greeks = _greek_view(normalized)
    gex = _gex_view(normalized)
    scenarios = _scenario_view(rows)
    concentration = _concentration_view(normalized)
    directional = _directional_view(normalized)
    regime_view = _regime_view(regime, directional, len(normalized))

    issues.extend(greeks.issues)
    issues.extend(gex.issues)
    issues.extend(scenarios.issues)
    issues.extend(exposure.issues)
    issues.extend(directional.issues)
    issues.extend(regime_view.issues)

    quality_states = tuple(p.quality for p in normalized)
    present = [q for q in quality_states if q is not None]
    merged_quality = max(present, key=lambda q: _QUALITY_RANK[q]) \
        if present else None

    status = PortfolioStatus.SUCCESS
    return PortfolioAnalyticsResult(
        status=status,
        positions=normalized,
        exposure=exposure,
        greeks=greeks,
        gex=gex,
        scenarios=scenarios,
        concentration=concentration,
        directional=directional,
        regime_risk=regime_view,
        quality=merged_quality,
        position_quality_states=quality_states,
        issues=tuple(issues),
        provenance=analysis_provenance,
        reference_timestamp=reference_timestamp,
        contract_version=CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )


def _invalid_result(
    positions: tuple,
    rows: tuple,
    reference_timestamp,
    provenance: Provenance | None,
    issue: PortfolioIssue,
) -> PortfolioAnalyticsResult:
    """Deterministic INVALID result — no analytics run across tenants."""
    (exposure, greeks, gex, scenarios, concentration,
     directional, regime_view) = _empty_exposure_views(positions)
    quality_states = tuple(getattr(p, "quality", None) for p in positions)
    present = [q for q in quality_states if q is not None]
    merged_quality = max(present, key=lambda q: _QUALITY_RANK[q]) \
        if present else None
    scenarios = PortfolioScenarioSensitivity(
        state=EvidenceState.UNAVAILABLE,
        rows=rows,
        point_count=len(rows),
        complete_rows=sum(1 for r in rows if not r.partial),
        partial_rows=sum(1 for r in rows if r.partial),
        worst_supplied_pnl=None,
        worst_supplied_point_id=None,
        best_supplied_pnl=None,
    )
    return PortfolioAnalyticsResult(
        status=PortfolioStatus.INVALID,
        positions=positions,
        exposure=exposure,
        greeks=greeks,
        gex=gex,
        scenarios=scenarios,
        concentration=concentration,
        directional=directional,
        regime_risk=regime_view,
        quality=merged_quality,
        position_quality_states=quality_states,
        issues=(issue,),
        provenance=provenance,
        reference_timestamp=reference_timestamp,
        contract_version=CONTRACT_VERSION,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )
