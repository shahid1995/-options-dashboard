"""Day 35 — Portfolio Intelligence tests (TDD, genuine repository contracts).

Proves the deterministic, broker-neutral portfolio-analytics boundary:

    authoritative positions (paper Position / broker-observed rows)
        -> normalization -> PortfolioPosition
        -> analytics (exposure / Greeks / GEX / scenarios / concentration /
                      directional / regime-aware views)
        -> PortfolioAnalyticsResult

Rules locked here
-----------------
1. Portfolio Intelligence consumes authoritative position truth; it never
   invents broker/paper quantities, fills or account state.
2. Paper ``Position`` net quantity remains authoritative for paper; broker
   positions remain authoritative for broker portfolios.
3. Missing values stay missing (never zero); explicit AVAILABLE/PARTIAL/
   UNAVAILABLE/INVALID assessment states are preserved.
4. Portfolio-owned GEX (raw_gex methodology on the portfolio's own gamma /
   contracts / spot) is NEVER the market/dealer GEX.
5. Directional exposure is descriptive: net delta is not a prediction, a
   probability, a trade signal or an execution recommendation.
6. A Day-23 regime label alone never fabricates directional evidence.
7. Provenance (Day-9) and quality (Day-9 vocabulary) are preserved, never
   synthesized.
8. Deterministic: caller-supplied reference timestamp only; no wall clock,
   no randomness, no DB/network/filesystem/broker I/O in the domain.
9. Portfolio analytics != central risk policy decision: no PASS/BLOCKED
   vocabulary, no order/execution/capital/margin/approval semantics.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.market_data.contracts import (
    Provenance,
    QualityState,
    Side,
)
from app.portfolio_intelligence.analytics import analyze_portfolio
from app.portfolio_intelligence.contracts import (
    CALCULATION_VERSION,
    CONTRACT_VERSION,
    GREEKS_SOURCE_BROKER,
    GREEKS_SOURCE_MODEL,
    MODEL_VERSION,
    ConcentrationView,
    DeltaPosture,
    EvidenceState,
    GreekInput,
    PortfolioAnalyticsResult,
    PortfolioExposure,
    PortfolioGexExposure,
    PortfolioGreekExposure,
    PortfolioIssueCode,
    PortfolioPosition,
    PortfolioScenarioSensitivity,
    PortfolioStatus,
    PositionSource,
    RegimeRiskView,
    DirectionalView,
    portfolio_result_from_dict,
    portfolio_result_to_dict,
)
from app.portfolio_intelligence.normalization import (
    broker_position_to_input,
    paper_position_to_input,
)
from app.quant.scenarios import OptionLeg, PositionDirection

# ---------------------------------------------------------------------------
# Shared genuine fixtures
# ---------------------------------------------------------------------------

REF = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
NIFTY = "NIFTY"
EXPIRY = "2026-09-24"
EXPIRY2 = "2026-10-29"


def _prov(source: str = "test.portfolio.v1") -> Provenance:
    return Provenance(
        source=source,
        collection_mode="BROKER_SNAPSHOT",
        received_at=REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _pos(
    *,
    position_id: str = "pos-1",
    tenant_id: str = "tenant-A",
    source: PositionSource = PositionSource.PAPER,
    option_type: Side = Side.CALL,
    strike: float = 20000.0,
    expiry: str = EXPIRY,
    quantity: float = 1.0,
    direction: PositionDirection = PositionDirection.LONG,
    lot_size: int = 75,
    entry_price: float | None = 100.0,
    current_price: float | None = None,
    market_value: float | None = None,
    spot: float | None = None,
    greeks: GreekInput | None = None,
    quality: QualityState | None = QualityState.EXCELLENT,
    provenance: Provenance | None = None,
    reference_timestamp: datetime = REF,
) -> PortfolioPosition:
    return PortfolioPosition(
        position_id=position_id,
        tenant_id=tenant_id,
        source=source,
        underlying=NIFTY,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        quantity=quantity,
        direction=direction,
        lot_size=lot_size,
        entry_price=entry_price,
        current_price=current_price,
        market_value=market_value,
        spot=spot,
        greeks=greeks,
        quality=quality,
        provenance=provenance if provenance is not None else _prov(),
        reference_timestamp=reference_timestamp,
    )


def _greeks(
    *,
    delta: float | None = 0.5,
    gamma: float | None = 0.0001,
    theta: float | None = -10.0,
    vega: float | None = 5.0,
    rho: float | None = 2.0,
    source: str = GREEKS_SOURCE_MODEL,
    provenance: Provenance | None = None,
) -> GreekInput:
    return GreekInput(
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho,
        source=source,
        quality=QualityState.EXCELLENT,
        provenance=provenance if provenance is not None else _prov("model-greeks"),
        calc_model="BLACK_SCHOLES_EUROPEAN",
        calc_version="1.0.0",
    )


def _analyze(positions, **kwargs):
    kwargs.setdefault("regime", None)
    kwargs.setdefault("scenario_rows", ())
    kwargs.setdefault("reference_timestamp", REF)
    return analyze_portfolio(positions, **kwargs)


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------


class TestPositionContract:
    def test_valid_position_constructs(self):
        p = _pos()
        assert p.position_id == "pos-1"
        assert p.source is PositionSource.PAPER
        assert p.option_type is Side.CALL
        assert p.direction is PositionDirection.LONG
        assert p.quantity == 1.0
        assert p.reference_timestamp == REF

    def test_rejects_naive_reference_timestamp(self):
        with pytest.raises(ValueError):
            _pos(reference_timestamp=datetime(2026, 9, 4, 10, 0))

    def test_rejects_zero_quantity_position(self):
        with pytest.raises(ValueError):
            _pos(quantity=0.0)

    def test_rejects_negative_quantity(self):
        with pytest.raises(ValueError):
            _pos(quantity=-1.0)

    def test_rejects_invalid_option_type(self):
        with pytest.raises(ValueError):
            _pos(option_type="weird")  # type: ignore[arg-type]

    def test_rejects_nonpositive_strike(self):
        with pytest.raises(ValueError):
            _pos(strike=0.0)

    def test_rejects_non_iso_expiry(self):
        with pytest.raises(ValueError):
            _pos(expiry="24/09/2026")

    def test_rejects_unknown_greeks_source(self):
        with pytest.raises(ValueError):
            _pos(greeks=_greeks(source="UNKNOWN"))


class TestGreekInputContract:
    def test_greeks_missing_fields_stay_none(self):
        g = _greeks(delta=None, gamma=None, rho=None)
        assert g.delta is None and g.gamma is None and g.rho is None

    def test_invalid_greeks_value_rejected(self):
        with pytest.raises(ValueError):
            _greeks(delta=float("nan"))


# ---------------------------------------------------------------------------
# 1. Empty portfolio
# ---------------------------------------------------------------------------


class TestEmptyPortfolio:
    def test_empty_portfolio_is_measured_zero(self):
        result = _analyze([])
        assert result.status is PortfolioStatus.SUCCESS
        assert result.positions == ()
        assert result.exposure.state is EvidenceState.AVAILABLE
        assert result.exposure.signed_quantity_total == 0.0
        assert result.exposure.position_count == 0
        assert result.greeks.state is EvidenceState.UNAVAILABLE
        assert result.gex.state is EvidenceState.UNAVAILABLE
        assert result.scenarios.state is EvidenceState.UNAVAILABLE
        assert result.concentration.state is EvidenceState.UNAVAILABLE
        assert result.directional.state is EvidenceState.UNAVAILABLE
        assert result.directional.delta_posture is DeltaPosture.NO_DELTA_EVIDENCE


# ---------------------------------------------------------------------------
# 2-8. Single / mixed / multi-expiry / netting / sign handling
# ---------------------------------------------------------------------------


class TestExposureAnalytics:
    def test_single_long_call_exposure(self):
        result = _analyze([_pos(quantity=2.0)])
        assert result.exposure.signed_quantity_total == 2.0
        assert result.exposure.long_quantity_total == 2.0
        assert result.exposure.short_quantity_total == 0.0
        assert result.exposure.position_count == 1

    def test_single_short_call_exposure(self):
        result = _analyze([_pos(quantity=3.0, direction=PositionDirection.SHORT)])
        assert result.exposure.signed_quantity_total == -3.0
        assert result.exposure.short_quantity_total == 3.0

    def test_mixed_ce_pe_netting(self):
        result = _analyze([
            _pos(position_id="ce", option_type=Side.CALL, quantity=5.0),
            _pos(position_id="pe", option_type=Side.PUT, quantity=2.0),
        ])
        assert result.exposure.signed_quantity_total == 7.0

    def test_long_short_netting_behaviour(self):
        # Same instrument long 5 / short 2 does NOT net in this layer: the
        # authoritative Position rows are already netted by the paper engine;
        # the analytics layer sums signed quantities as supplied (5 + -2 = 3)
        # and records both contributor rows.
        result = _analyze([
            _pos(position_id="long-leg", quantity=5.0),
            _pos(position_id="short-leg", quantity=2.0,
                 direction=PositionDirection.SHORT),
        ])
        assert result.exposure.signed_quantity_total == 3.0
        assert result.exposure.long_quantity_total == 5.0
        assert result.exposure.short_quantity_total == 2.0

    def test_multi_expiry_exposure(self):
        result = _analyze([
            _pos(position_id="e1", expiry=EXPIRY, quantity=1.0),
            _pos(position_id="e2", expiry=EXPIRY2, quantity=4.0,
                 direction=PositionDirection.SHORT),
        ])
        assert result.exposure.signed_quantity_total == -3.0
        by_expiry = {s.key: s for s in result.exposure.by_expiry}
        assert by_expiry[EXPIRY].signed_quantity == 1.0
        assert by_expiry[EXPIRY2].signed_quantity == -4.0

    def test_signed_quantity_uses_direction_not_action_string(self):
        # A paper row is net quantity signed; the input direction must be the
        # ONLY sign authority (never inferred from a label).
        p = _pos(direction=PositionDirection.SHORT, quantity=7.0)
        assert p.direction.sign * p.quantity == -7.0

    def test_market_value_total_only_over_observed(self):
        result = _analyze([
            _pos(position_id="a", market_value=1000.0),
            _pos(position_id="b", market_value=None),
        ])
        assert result.exposure.market_value_total == 1000.0
        assert result.exposure.market_value_positions == 1
        assert "b" in result.exposure.positions_missing_market_value


# ---------------------------------------------------------------------------
# 9-10. Greek aggregation and missing Greeks
# ---------------------------------------------------------------------------


class TestGreekAnalytics:
    def test_delta_gamma_theta_vega_rho_aggregation(self):
        # exposure-scaled greek = per-unit greek x direction.sign x quantity
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5,
                                                                gamma=0.0002,
                                                                theta=-5.0,
                                                                vega=4.0,
                                                                rho=1.0)),
            _pos(position_id="b", quantity=1.0, direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=0.6, gamma=0.0001, theta=-3.0, vega=2.0,
                                rho=0.5)),
        ])
        g = result.greeks
        assert g.state is EvidenceState.AVAILABLE
        # Single source (MODEL by default) -> its totals are exposed alone.
        assert len(g.by_source) == 1
        src = g.by_source[0]
        assert src.source == GREEKS_SOURCE_MODEL
        assert src.delta_total == pytest.approx(2.0 * 0.5 - 1.0 * 0.6)
        assert src.gamma_total == pytest.approx(2.0 * 0.0002 - 0.0001)
        assert src.theta_total == pytest.approx(2.0 * -5.0 - 1.0 * -3.0)
        assert src.vega_total == pytest.approx(2.0 * 4.0 - 2.0)
        assert src.rho_total == pytest.approx(2.0 * 1.0 - 0.5)

    def test_missing_greek_is_not_zero(self):
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5)),
            _pos(position_id="b", quantity=1.0, greeks=_greeks(delta=None)),
        ])
        g = result.greeks
        # Delta available for one of two positions -> PARTIAL, sum over present
        assert len(g.by_source) == 1
        assert g.by_source[0].source == GREEKS_SOURCE_MODEL
        assert g.by_source[0].delta_total == pytest.approx(1.0)
        assert g.state is EvidenceState.PARTIAL
        assert "b" in g.missing_positions

    def test_all_missing_greeks_unavailable(self):
        result = _analyze([
            _pos(position_id="a", greeks=_greeks(delta=None, gamma=None,
                                                 theta=None, vega=None,
                                                 rho=None)),
        ])
        # The MODEL source was attempted but supplied no Greek -> the
        # source entry is UNAVAILABLE with every total None (never zero).
        assert len(result.greeks.by_source) == 1
        src = result.greeks.by_source[0]
        assert src.source == GREEKS_SOURCE_MODEL
        assert src.state is EvidenceState.UNAVAILABLE
        assert src.delta_total is None
        assert result.greeks.state is EvidenceState.UNAVAILABLE

    def test_no_greeks_at_all_unavailable(self):
        result = _analyze([_pos(greeks=None)])
        assert result.greeks.state is EvidenceState.UNAVAILABLE

    def test_greek_source_preserved_per_contribution(self):
        result = _analyze([
            _pos(position_id="a", greeks=_greeks(source=GREEKS_SOURCE_MODEL)),
            _pos(position_id="b", greeks=_greeks(source=GREEKS_SOURCE_BROKER)),
        ])
        sources = set()
        for c in result.greeks.contributions:
            sources.add(c.greeks_source)
        assert sources == {GREEKS_SOURCE_MODEL, GREEKS_SOURCE_BROKER}
        # Broker and model greeks are never silently mixed in one total.
        assert result.greeks.sources == (GREEKS_SOURCE_BROKER, GREEKS_SOURCE_MODEL)

    def test_broker_and_model_delta_never_mix_into_one_total(self):
        """The confirmed defect: BROKER +50 and MODEL -20 must NOT become +30.

        Source identity must survive at aggregate level; no synthetic
        combined total may exist.
        """
        result = _analyze([
            _pos(position_id="broker-pos", greeks=_greeks(
                delta=50.0, source=GREEKS_SOURCE_BROKER)),
            _pos(position_id="model-pos", greeks=_greeks(
                delta=-20.0, source=GREEKS_SOURCE_MODEL)),
        ])
        by_source = {entry.source: entry
                     for entry in result.greeks.by_source}
        assert set(by_source) == {GREEKS_SOURCE_BROKER, GREEKS_SOURCE_MODEL}
        assert by_source[GREEKS_SOURCE_BROKER].delta_total == pytest.approx(50.0)
        assert by_source[GREEKS_SOURCE_MODEL].delta_total == pytest.approx(-20.0)
        # The contract exposes NO mixed scalar total (nor any other field
        # that could hide broker+model in one number).
        assert not hasattr(result.greeks, "delta_total")
        payload = json.dumps(portfolio_result_to_dict(result))
        assert '"delta_total": 30' not in payload

    def test_broker_only_aggregation_exposed_normally(self):
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(
                delta=0.5, gamma=0.0002, theta=-5.0, vega=4.0, rho=1.0,
                source=GREEKS_SOURCE_BROKER)),
            _pos(position_id="b", quantity=1.0,
                 direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=0.6, gamma=0.0001, theta=-3.0, vega=2.0,
                                rho=0.5, source=GREEKS_SOURCE_BROKER)),
        ])
        assert len(result.greeks.by_source) == 1
        src = result.greeks.by_source[0]
        assert src.source == GREEKS_SOURCE_BROKER
        assert src.delta_total == pytest.approx(2.0 * 0.5 - 1.0 * 0.6)
        assert src.gamma_total == pytest.approx(2.0 * 0.0002 - 0.0001)
        assert src.theta_total == pytest.approx(2.0 * -5.0 - 1.0 * -3.0)
        assert src.vega_total == pytest.approx(2.0 * 4.0 - 2.0)
        assert src.rho_total == pytest.approx(2.0 * 1.0 - 0.5)
        assert src.state is EvidenceState.AVAILABLE
        assert src.contributing_positions == ("a", "b")
        assert src.missing_positions == ()

    def test_model_only_aggregation_exposed_normally(self):
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5)),
            _pos(position_id="b", quantity=1.0,
                 direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=0.6)),
        ])
        assert len(result.greeks.by_source) == 1
        src = result.greeks.by_source[0]
        assert src.source == GREEKS_SOURCE_MODEL
        assert src.delta_total == pytest.approx(2.0 * 0.5 - 1.0 * 0.6)
        assert src.state is EvidenceState.AVAILABLE

    def test_all_five_greeks_preserve_source_separation(self):
        result = _analyze([
            _pos(position_id="b", greeks=_greeks(
                delta=50.0, gamma=0.01, theta=-100.0, vega=40.0, rho=10.0,
                source=GREEKS_SOURCE_BROKER)),
            _pos(position_id="m", greeks=_greeks(
                delta=-20.0, gamma=0.004, theta=30.0, vega=-5.0, rho=-2.0,
                source=GREEKS_SOURCE_MODEL)),
        ])
        by = {entry.source: entry for entry in result.greeks.by_source}
        assert by[GREEKS_SOURCE_BROKER].delta_total == pytest.approx(50.0)
        assert by[GREEKS_SOURCE_MODEL].delta_total == pytest.approx(-20.0)
        assert by[GREEKS_SOURCE_BROKER].gamma_total == pytest.approx(0.01)
        assert by[GREEKS_SOURCE_MODEL].gamma_total == pytest.approx(0.004)
        assert by[GREEKS_SOURCE_BROKER].theta_total == pytest.approx(-100.0)
        assert by[GREEKS_SOURCE_MODEL].theta_total == pytest.approx(30.0)
        assert by[GREEKS_SOURCE_BROKER].vega_total == pytest.approx(40.0)
        assert by[GREEKS_SOURCE_MODEL].vega_total == pytest.approx(-5.0)
        assert by[GREEKS_SOURCE_BROKER].rho_total == pytest.approx(10.0)
        assert by[GREEKS_SOURCE_MODEL].rho_total == pytest.approx(-2.0)

    def test_missing_model_greek_stays_missing_when_broker_present(self):
        result = _analyze([
            _pos(position_id="b", greeks=_greeks(
                delta=50.0, source=GREEKS_SOURCE_BROKER)),
            _pos(position_id="m", greeks=_greeks(
                delta=None, gamma=0.004, theta=None, vega=None, rho=None,
                source=GREEKS_SOURCE_MODEL)),
        ])
        by = {entry.source: entry for entry in result.greeks.by_source}
        # Broker delta is observed; model delta is genuinely missing and is
        # NEVER converted to zero.
        assert by[GREEKS_SOURCE_BROKER].delta_total == pytest.approx(50.0)
        assert by[GREEKS_SOURCE_MODEL].delta_total is None
        assert by[GREEKS_SOURCE_MODEL].gamma_total == pytest.approx(0.004)
        assert by[GREEKS_SOURCE_MODEL].state is EvidenceState.PARTIAL
        assert result.greeks.state is EvidenceState.PARTIAL

    def test_source_totals_traceable_with_quality_and_provenance(self):
        result = _analyze([
            _pos(position_id="b", greeks=_greeks(
                delta=50.0, source=GREEKS_SOURCE_BROKER,
                provenance=_prov("broker-greeks"))),
            _pos(position_id="m", greeks=_greeks(
                delta=-20.0, source=GREEKS_SOURCE_MODEL,
                provenance=_prov("model-greeks"))),
        ])
        by = {entry.source: entry for entry in result.greeks.by_source}
        assert by[GREEKS_SOURCE_BROKER].contributing_positions == ("b",)
        assert by[GREEKS_SOURCE_MODEL].contributing_positions == ("m",)
        contrib_by_id = {c.position_id: c for c in result.greeks.contributions}
        assert contrib_by_id["b"].greeks_source == GREEKS_SOURCE_BROKER
        assert contrib_by_id["b"].quality is QualityState.EXCELLENT
        assert contrib_by_id["b"].provenance is not None
        assert contrib_by_id["m"].greeks_source == GREEKS_SOURCE_MODEL
        assert contrib_by_id["m"].quality is QualityState.EXCELLENT
        assert contrib_by_id["m"].provenance is not None

    def test_mixed_source_deterministic_order_and_round_trip(self):
        def run():
            return _analyze([
                _pos(position_id="broker-pos", greeks=_greeks(
                    delta=50.0, gamma=0.01, theta=-100.0, vega=40.0,
                    rho=10.0, source=GREEKS_SOURCE_BROKER)),
                _pos(position_id="model-pos", greeks=_greeks(
                    delta=-20.0, gamma=0.004, theta=30.0, vega=-5.0,
                    rho=-2.0, source=GREEKS_SOURCE_MODEL)),
            ])

        result = run()
        assert [e.source for e in result.greeks.by_source] == [
            GREEKS_SOURCE_BROKER, GREEKS_SOURCE_MODEL]
        # Repeated execution is byte-identical.
        assert json.dumps(portfolio_result_to_dict(result),
                          sort_keys=True) == json.dumps(
            portfolio_result_to_dict(run()), sort_keys=True)
        # Deterministic serialization round-trips the separated totals.
        restored = portfolio_result_from_dict(portfolio_result_to_dict(result))
        assert [e.source for e in restored.greeks.by_source] == [
            GREEKS_SOURCE_BROKER, GREEKS_SOURCE_MODEL]
        assert restored.greeks.by_source[0].delta_total == pytest.approx(50.0)
        assert restored.greeks.by_source[1].delta_total == pytest.approx(-20.0)


# ---------------------------------------------------------------------------
# 11-12. GEX aggregation + missing GEX (portfolio-owned, not dealer GEX)
# ---------------------------------------------------------------------------


class TestGexAnalytics:
    def test_portfolio_gex_is_not_market_gex(self):
        # Portfolio-owned GEX uses the SAME raw_gex formula over the
        # portfolio's own gamma x own contracts x spot — never market OI.
        from app.quant.gex import raw_gex

        pos = _pos(position_id="a", quantity=2.0, spot=20000.0,
                   greeks=_greeks(gamma=0.0001))
        result = _analyze([pos])
        total = result.gex.by_source[0].signed_gex_total
        # 2 lots x 75 lot size = 150 own contracts
        assert total == pytest.approx(raw_gex(0.0001, 150.0, 20000.0))
        assert result.gex.methodology == "GEX_STANDARD_V1"

    def test_short_position_flips_portfolio_gex_sign(self):
        from app.quant.gex import raw_gex

        long = _pos(position_id="a", quantity=1.0, spot=20000.0,
                    greeks=_greeks(gamma=0.0001))
        short = _pos(position_id="b", quantity=1.0,
                     direction=PositionDirection.SHORT, spot=20000.0,
                     greeks=_greeks(gamma=0.0001))
        result_long = _analyze([long]).gex.by_source[0].signed_gex_total
        result_short = _analyze([short]).gex.by_source[0].signed_gex_total
        expected = raw_gex(0.0001, 75.0, 20000.0)
        assert result_long == pytest.approx(expected)
        assert result_short == pytest.approx(-expected)

    def test_missing_gamma_gex_unavailable_not_zero(self):
        result = _analyze([
            _pos(position_id="a", quantity=1.0, spot=20000.0,
                 greeks=_greeks(gamma=None)),
        ])
        assert result.gex.state is EvidenceState.UNAVAILABLE
        assert result.gex.by_source[0].signed_gex_total is None

    def test_missing_spot_gex_unavailable_not_zero(self):
        result = _analyze([
            _pos(position_id="a", quantity=1.0, spot=None,
                 greeks=_greeks(gamma=0.0001)),
        ])
        assert result.gex.state is EvidenceState.UNAVAILABLE

    def test_partial_gamma_coverage_is_partial(self):
        result = _analyze([
            _pos(position_id="a", quantity=1.0, spot=20000.0,
                 greeks=_greeks(gamma=0.0001)),
            _pos(position_id="b", quantity=1.0, spot=20000.0,
                 greeks=_greeks(gamma=None)),
        ])
        assert result.gex.state is EvidenceState.PARTIAL

    def test_gex_source_separation(self):
        result = _analyze([
            _pos(position_id="a", quantity=1.0, spot=20000.0,
                 greeks=_greeks(gamma=0.0001, source=GREEKS_SOURCE_MODEL)),
            _pos(position_id="b", quantity=1.0, spot=20000.0,
                 greeks=_greeks(gamma=0.0001, source=GREEKS_SOURCE_BROKER)),
        ])
        assert len(result.gex.by_source) == 2


# ---------------------------------------------------------------------------
# 13-14. Scenario aggregation + missing scenario
# ---------------------------------------------------------------------------


class TestScenarioAnalytics:
    def test_scenario_rows_aggregate(self):
        from app.portfolio_intelligence.contracts import ScenarioRow

        rows = (
            ScenarioRow(tenant_id="tenant-A", point_id="p1", spot=19900.0,
                        time_to_expiry=0.01, implied_volatility=0.2,
                        total_pnl=-5000.0, partial=False,
                        provenance=_prov("scenario")),
            ScenarioRow(tenant_id="tenant-A", point_id="p2", spot=20000.0,
                        time_to_expiry=0.01, implied_volatility=0.2,
                        total_pnl=1000.0, partial=False,
                        provenance=_prov("scenario")),
        )
        result = _analyze([_pos()], scenario_rows=rows)
        s = result.scenarios
        assert s.state is EvidenceState.AVAILABLE
        assert s.point_count == 2
        assert s.complete_rows == 2
        assert s.worst_supplied_pnl == -5000.0
        assert s.worst_supplied_point_id == "p1"
        assert s.best_supplied_pnl == 1000.0

    def test_missing_scenario_rows_unavailable(self):
        result = _analyze([_pos()], scenario_rows=())
        assert result.scenarios.state is EvidenceState.UNAVAILABLE
        assert result.scenarios.point_count == 0

    def test_partial_scenario_rows_preserved(self):
        from app.portfolio_intelligence.contracts import ScenarioRow

        rows = (
            ScenarioRow(tenant_id="tenant-A", point_id="p1", spot=19900.0,
                        time_to_expiry=0.01, implied_volatility=0.2,
                        total_pnl=-5000.0, partial=False,
                        provenance=_prov("scenario")),
            ScenarioRow(tenant_id="tenant-A", point_id="p2", spot=20000.0,
                        time_to_expiry=0.01, implied_volatility=0.2,
                        total_pnl=None, partial=True,
                        provenance=_prov("scenario")),
        )
        result = _analyze([_pos()], scenario_rows=rows)
        s = result.scenarios
        assert s.partial_rows == 1
        # pnl aggregated only over complete rows; the partial row never
        # contributes a zero P/L.
        assert s.worst_supplied_pnl == -5000.0
        assert s.point_count == 2

    def test_scenario_row_tenant_must_match_portfolio(self):
        from app.portfolio_intelligence.contracts import ScenarioRow

        rows = (
            ScenarioRow(tenant_id="tenant-B", point_id="p1", spot=19900.0,
                        time_to_expiry=0.01, implied_volatility=0.2,
                        total_pnl=-5000.0, partial=False,
                        provenance=_prov("scenario")),
        )
        result = _analyze([_pos(tenant_id="tenant-A")], scenario_rows=rows)
        assert result.status is PortfolioStatus.INVALID


# ---------------------------------------------------------------------------
# 15-18. Concentration
# ---------------------------------------------------------------------------


class TestConcentrationView:
    def test_concentration_by_strike(self):
        result = _analyze([
            _pos(position_id="a", strike=20000.0, quantity=8.0),
            _pos(position_id="b", strike=20500.0, quantity=2.0),
        ])
        c = result.concentration
        assert c.state is EvidenceState.AVAILABLE
        by_strike = {s.key: s for s in c.by_strike}
        assert by_strike["20000.0"].share == pytest.approx(0.8)
        assert by_strike["20500.0"].share == pytest.approx(0.2)

    def test_concentration_by_expiry(self):
        result = _analyze([
            _pos(position_id="a", expiry=EXPIRY, quantity=3.0),
            _pos(position_id="b", expiry=EXPIRY2, quantity=1.0),
        ])
        by_expiry = {s.key: s for s in result.concentration.by_expiry}
        assert by_expiry[EXPIRY].share == pytest.approx(0.75)
        assert by_expiry[EXPIRY2].share == pytest.approx(0.25)

    def test_concentration_by_option_type(self):
        result = _analyze([
            _pos(position_id="a", option_type=Side.CALL, quantity=9.0),
            _pos(position_id="b", option_type=Side.PUT, quantity=1.0),
        ])
        by_type = {s.key: s for s in result.concentration.by_option_type}
        assert by_type["CALL"].share == pytest.approx(0.9)
        assert by_type["PUT"].share == pytest.approx(0.1)

    def test_largest_absolute_exposure(self):
        result = _analyze([
            _pos(position_id="small", quantity=2.0),
            _pos(position_id="big", quantity=10.0,
                 direction=PositionDirection.SHORT),
        ])
        assert result.concentration.largest_absolute is not None
        assert result.concentration.largest_absolute.position_id == "big"
        assert result.concentration.largest_absolute.absolute_exposure == 10.0

    def test_concentration_is_measurement_not_verdict(self):
        # No threshold language exists on the view: nothing says danger.
        result = _analyze([_pos(quantity=100.0)])
        fields = {f for f in result.concentration.__dataclass_fields__}
        assert not {"danger", "high_risk", "recommendation"} & fields
        assert result.concentration.by_option_type[0].share == pytest.approx(1.0)

    def test_concentration_uses_absolute_quantity_basis(self):
        result = _analyze([
            _pos(position_id="a", quantity=3.0, direction=PositionDirection.LONG),
            _pos(position_id="b", quantity=1.0, direction=PositionDirection.SHORT),
        ])
        assert result.concentration.by_option_type[0].share == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 19-21. Directional view + regime non-fabrication
# ---------------------------------------------------------------------------


class TestDirectionalView:
    def test_net_delta_long(self):
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5)),
        ])
        d = result.directional
        assert d.net_delta == pytest.approx(1.0)
        assert d.delta_posture is DeltaPosture.LONG_DELTA
        assert d.state is EvidenceState.AVAILABLE

    def test_net_delta_short(self):
        result = _analyze([
            _pos(position_id="a", quantity=2.0, direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=0.5)),
        ])
        assert result.directional.delta_posture is DeltaPosture.SHORT_DELTA

    def test_no_delta_evidence(self):
        result = _analyze([_pos(greeks=None)])
        assert result.directional.delta_posture is DeltaPosture.NO_DELTA_EVIDENCE
        assert result.directional.state is EvidenceState.UNAVAILABLE

    def test_delta_neutral_measured_zero(self):
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5)),
            _pos(position_id="b", quantity=1.0, direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=1.0)),
        ])
        assert result.directional.net_delta == pytest.approx(0.0)
        assert result.directional.delta_posture is DeltaPosture.DELTA_NEUTRAL

    def test_ce_pe_delta_contributions(self):
        result = _analyze([
            _pos(position_id="call-leg", option_type=Side.CALL, quantity=2.0,
                 greeks=_greeks(delta=0.5)),
            _pos(position_id="put-leg", option_type=Side.PUT, quantity=1.0,
                 greeks=_greeks(delta=-0.4)),
        ])
        assert result.directional.call_delta == pytest.approx(1.0)
        assert result.directional.put_delta == pytest.approx(-0.4)

    def test_no_prediction_vocabulary(self):
        # A positive net delta never becomes a probability or a forecast.
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5)),
        ])
        assert result.directional.delta_posture is DeltaPosture.LONG_DELTA
        assert not any("bull" in i.message.lower()
                       for i in result.issues)
        # The view exposes numbers and a descriptive posture, nothing else.
        assert not hasattr(result.directional, "probability")


class TestRegimeView:
    def test_no_regime_input_unknown(self):
        result = _analyze([_pos(greeks=_greeks(delta=0.5))], regime=None)
        r = result.regime_risk
        assert r.state is EvidenceState.UNAVAILABLE
        assert r.regime is None
        assert any("unknown" in n.lower() for n in r.notes)

    def test_unknown_regime_label_remains_unknown(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        regime = MarketRegime(label=RegimeLabel.UNKNOWN, source="test.regime",
                              reference_timestamp=REF)
        result = _analyze([_pos(greeks=_greeks(delta=0.5))], regime=regime)
        assert result.regime_risk.state is EvidenceState.UNAVAILABLE
        # No directional guess from the label
        assert result.regime_risk.net_delta_context is None

    def test_regime_label_never_fabricates_direction(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        # TRENDING label + NO delta evidence must NOT yield any direction.
        regime = MarketRegime(label=RegimeLabel.TRENDING, source="test.regime",
                              model_version="1.0.0", reference_timestamp=REF)
        result = _analyze([_pos(greeks=None)], regime=regime)
        assert result.directional.delta_posture is DeltaPosture.NO_DELTA_EVIDENCE
        assert result.regime_risk.state is EvidenceState.PARTIAL
        assert result.regime_risk.regime is regime
        # The regime label is contextual only — no delta is fabricated.
        assert result.regime_risk.net_delta_context is None

    def test_regime_with_delta_describes_context_only(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        regime = MarketRegime(label=RegimeLabel.TRENDING, source="test.regime",
                              model_version="1.0.0", reference_timestamp=REF)
        result = _analyze([
            _pos(position_id="a", quantity=2.0, greeks=_greeks(delta=0.5)),
        ], regime=regime)
        r = result.regime_risk
        assert r.state is EvidenceState.AVAILABLE
        assert r.net_delta_context == pytest.approx(1.0)
        assert r.regime_label is RegimeLabel.TRENDING
        assert any("contextual" in n.lower() for n in r.notes)

    def test_regime_preserved_verbatim(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        regime = MarketRegime(label=RegimeLabel.RANGING, source="day23.regime",
                              model_version="2.1.0", reference_timestamp=REF)
        result = _analyze([_pos()], regime=regime)
        assert result.regime_risk.regime is regime
        assert result.regime_risk.regime_label is RegimeLabel.RANGING


# ---------------------------------------------------------------------------
# 22. Broker/model source separation
# ---------------------------------------------------------------------------


class TestSourceSeparation:
    def test_position_source_paper_vs_broker_preserved(self):
        paper = _pos(position_id="a", source=PositionSource.PAPER)
        broker = _pos(position_id="b", source=PositionSource.BROKER,
                      market_value=5000.0)
        result = _analyze([paper, broker])
        sources = {p.source for p in result.positions}
        assert sources == {PositionSource.PAPER, PositionSource.BROKER}
        # broker market value never leaks into a paper-derived claim: totals
        # are computed only where observed.
        assert result.exposure.market_value_total == 5000.0

    def test_broker_observed_value_not_rewritten(self):
        broker = _pos(position_id="b", source=PositionSource.BROKER,
                      market_value=12345.0)
        result = _analyze([broker])
        assert result.exposure.market_value_total == 12345.0
        # the layer never claims a different value than observed
        assert result.positions[0].market_value == 12345.0


# ---------------------------------------------------------------------------
# 23-24. Provenance and quality preservation
# ---------------------------------------------------------------------------


class TestProvenanceQuality:
    def test_provenance_preserved_on_positions_and_greeks(self):
        pprov = _prov("paper.row.v1")
        gprov = _prov("model.greeks.v1")
        p = _pos(provenance=pprov, greeks=_greeks(provenance=gprov))
        result = _analyze([p])
        assert result.positions[0].provenance is pprov
        assert result.positions[0].greeks.provenance is gprov
        # greek contribution preserves its greek-level provenance
        assert result.greeks.contributions[0].provenance is gprov

    def test_quality_preserved_never_upgraded(self):
        result = _analyze([
            _pos(position_id="good", quality=QualityState.EXCELLENT),
            _pos(position_id="bad", quality=QualityState.INSUFFICIENT),
        ])
        states = {q for q in result.position_quality_states}
        assert states == {QualityState.EXCELLENT, QualityState.INSUFFICIENT}
        # merged quality channel reflects the worst present state, and no
        # position quality is fabricated when all are missing.
        assert result.quality is QualityState.INSUFFICIENT

    def test_all_missing_quality_is_none_not_good(self):
        result = _analyze([
            _pos(position_id="a", quality=None),
            _pos(position_id="b", quality=None),
        ])
        assert result.quality is None
        assert result.position_quality_states == (None, None)


# ---------------------------------------------------------------------------
# 25-27. Determinism / caller-supplied timestamp / serialization
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_repeated_analysis_byte_identical(self):
        positions = [
            _pos(position_id="a", quantity=2.0, greeks=_greeks()),
            _pos(position_id="b", quantity=1.0, direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=0.6)),
        ]
        r1 = _analyze(positions)
        r2 = _analyze(positions)
        b1 = json.dumps(portfolio_result_to_dict(r1), sort_keys=True)
        b2 = json.dumps(portfolio_result_to_dict(r2), sort_keys=True)
        assert b1 == b2

    def test_serialization_round_trip(self):
        positions = [
            _pos(position_id="a", quantity=2.0, greeks=_greeks()),
            _pos(position_id="b", quantity=1.0, direction=PositionDirection.SHORT,
                 greeks=_greeks(delta=0.6)),
        ]
        r = _analyze(positions)
        restored = portfolio_result_from_dict(portfolio_result_to_dict(r))
        assert restored == r

    def test_serialization_is_json_safe(self):
        r = _analyze([_pos(quantity=1.0, greeks=_greeks())])
        payload = portfolio_result_to_dict(r)
        text = json.dumps(payload, sort_keys=True)
        assert isinstance(text, str)
        # deterministic bytes across two serializations
        assert text == json.dumps(payload, sort_keys=True)

    def test_naive_reference_timestamp_rejected(self):
        with pytest.raises(ValueError):
            _analyze([_pos()], reference_timestamp=datetime(2026, 9, 4))

    def test_missing_reference_timestamp_rejected(self):
        with pytest.raises(TypeError):
            analyze_portfolio([_pos()])  # reference_timestamp required


# ---------------------------------------------------------------------------
# 28. Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    def test_mixed_tenant_positions_invalid(self):
        result = _analyze([
            _pos(position_id="a", tenant_id="tenant-A"),
            _pos(position_id="b", tenant_id="tenant-B"),
        ])
        assert result.status is PortfolioStatus.INVALID
        assert any(i.code is PortfolioIssueCode.MIXED_TENANT for i in result.issues)

    def test_single_tenant_ok(self):
        result = _analyze([
            _pos(position_id="a", tenant_id="tenant-A"),
            _pos(position_id="b", tenant_id="tenant-A"),
        ])
        assert result.status is PortfolioStatus.SUCCESS


# ---------------------------------------------------------------------------
# 29-32. Authority + separation boundaries
# ---------------------------------------------------------------------------


class TestAuthorityBoundaries:
    def test_paper_position_authority(self):
        # The normalized quantity IS the paper net quantity (lots).  The
        # analytics never invents a different quantity.
        p = _pos(position_id="paper-1", source=PositionSource.PAPER,
                 quantity=4.0)
        result = _analyze([p])
        assert result.positions[0].source is PositionSource.PAPER
        assert result.exposure.signed_quantity_total == 4.0
        assert result.positions[0].quantity == 4.0

    def test_no_central_risk_vocabulary(self):
        result = _analyze([_pos()])
        # The result schema is analytic: no risk-policy/execution decision
        # vocabulary appears in any field name, message or enum value.
        def _strings(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield str(k)
                    yield from _strings(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    yield from _strings(v)
            elif isinstance(obj, str):
                yield obj

        text = " ".join(_strings(portfolio_result_to_dict(result))).upper()
        for banned in ("RISK_BLOCKED", "RISK_PARTIAL", "RISK_UNAVAILABLE",
                       "RISK_INVALID", "APPROVED", "EXECUTION", "MARGIN",
                       "CAPITAL", "AUTHORIZE"):
            assert banned not in text, f"found banned token {banned!r}"
        assert result.status is PortfolioStatus.SUCCESS

    def test_regime_risk_view_is_not_a_policy_decision(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        regime = MarketRegime(label=RegimeLabel.HIGH_VOLATILITY,
                              source="test.regime", reference_timestamp=REF)
        result = _analyze([_pos(greeks=_greeks(delta=0.5))], regime=regime)
        # The view carries descriptive fields only — no allow/deny verdict.
        assert not hasattr(result.regime_risk, "verdict")
        assert not hasattr(result.regime_risk, "approved")
        assert result.status is PortfolioStatus.SUCCESS

    def test_view_contracts_present_in_state(self):
        result = _analyze([_pos()])
        assert isinstance(result.exposure, PortfolioExposure)
        assert isinstance(result.greeks, PortfolioGreekExposure)
        assert isinstance(result.gex, PortfolioGexExposure)
        assert isinstance(result.scenarios, PortfolioScenarioSensitivity)
        assert isinstance(result.concentration, ConcentrationView)
        assert isinstance(result.directional, DirectionalView)
        assert isinstance(result.regime_risk, RegimeRiskView)
        assert isinstance(result, PortfolioAnalyticsResult)

    def test_versions_present(self):
        result = _analyze([_pos()])
        assert result.contract_version == CONTRACT_VERSION
        assert result.model_version == MODEL_VERSION
        assert result.calculation_version == CALCULATION_VERSION
        assert result.reference_timestamp == REF


# ---------------------------------------------------------------------------
# Integration: normalization from genuine repository contracts
# ---------------------------------------------------------------------------


class TestNormalizationIntegration:
    def _paper_row(self, **overrides):
        """A genuine ORM Position row (no DB required to construct)."""
        from app.models import Position

        values = dict(
            id=1, user_id="tenant-A", symbol="NIFTY", expiry=EXPIRY,
            strike=24350.0, option_type="call", net_quantity=3,
            average_entry_price=125.0, lot_size=65, realized_pnl=0.0,
            status="open", strategy_execution_id=None,
        )
        values.update(overrides)
        return Position(**values)

    def test_genuine_paper_position_normalizes(self):
        row = self._paper_row()
        p = paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF,
                                    greeks=_greeks(delta=0.5))
        assert p.source is PositionSource.PAPER
        assert p.option_type is Side.CALL
        assert p.quantity == 3.0
        assert p.direction is PositionDirection.LONG
        assert p.lot_size == 65
        assert p.entry_price == 125.0
        assert p.greeks is not None

    def test_net_short_paper_row_direction(self):
        row = self._paper_row(net_quantity=-2)
        p = paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF)
        assert p.direction is PositionDirection.SHORT
        assert p.quantity == 2.0

    def test_paper_row_requires_net_quantity(self):
        row = self._paper_row(net_quantity=0)
        with pytest.raises(ValueError):
            paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF)

    def test_closed_paper_row_rejected(self):
        row = self._paper_row(status="closed")
        with pytest.raises(ValueError):
            paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF)

    def test_broker_row_normalizes_and_preserves_observed_value(self):
        row = {
            "symbol": "NIFTY", "expiry": EXPIRY, "strike": 24350.0,
            "option_type": "call", "quantity": 5, "direction": "LONG",
            "lot_size": 65, "market_value": 408750.0,
        }
        p = broker_position_to_input(row, tenant_id="tenant-A",
                                     reference_timestamp=REF)
        assert p.source is PositionSource.BROKER
        assert p.market_value == 408750.0
        assert p.quantity == 5.0

    def test_broker_row_missing_quantity_never_fabricated(self):
        row = {
            "symbol": "NIFTY", "expiry": EXPIRY, "strike": 24350.0,
            "option_type": "call", "lot_size": 65,
        }
        with pytest.raises(ValueError):
            broker_position_to_input(row, tenant_id="tenant-A",
                                     reference_timestamp=REF)


# ---------------------------------------------------------------------------
# Integration: genuine repository contracts end to end
# ---------------------------------------------------------------------------


class TestGenuineIntegration:
    """The full chain with genuinely constructed repository objects:
    paper Position rows -> Day-15/18 model Greeks + Day-18 scenario outputs
    -> Day-23 regime -> Day-35 analytics."""

    def _paper_positions(self, db_user: str = "tenant-A"):
        from app.models import Position

        rows = [
            Position(
                id=1, user_id=db_user, symbol="NIFTY", expiry=EXPIRY,
                strike=24350.0, option_type="call", net_quantity=2,
                average_entry_price=125.0, lot_size=65, realized_pnl=0.0,
                status="open",
            ),
            Position(
                id=2, user_id=db_user, symbol="NIFTY", expiry=EXPIRY2,
                strike=24400.0, option_type="put", net_quantity=-1,
                average_entry_price=80.0, lot_size=65, realized_pnl=0.0,
                status="open",
            ),
        ]
        return rows

    def test_genuine_paper_positions_to_analytics(self):
        """Genuine paper Position rows normalize and analyze end to end."""
        from app.quant.contracts import CalculationContext
        from app.quant.scenarios import OptionLeg, PositionDirection
        from app.quant.scenarios import evaluate_leg_grid, ScenarioGrid

        rows = self._paper_positions()
        greeks = _greeks(delta=0.5, gamma=0.0001, theta=-8.0, vega=4.0, rho=1.0)
        positions = tuple(
            paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF, greeks=greeks)
            for row in rows
        )
        assert all(p.source is PositionSource.PAPER for p in positions)
        assert positions[0].signed_quantity == 2.0
        assert positions[1].signed_quantity == -1.0

        result = _analyze(positions)
        assert result.status is PortfolioStatus.SUCCESS
        assert result.exposure.position_count == 2
        assert result.exposure.signed_quantity_total == 1.0  # 2 - 1
        # Both paper rows carry MODEL greeks -> one source total.
        assert len(result.greeks.by_source) == 1
        assert result.greeks.by_source[0].source == GREEKS_SOURCE_MODEL
        assert result.greeks.by_source[0].delta_total == pytest.approx(0.5)

    def test_genuine_day18_scenario_rows_consumed(self):
        """Scenario rows computed by the REAL Day-18 engine feed the view."""
        from app.quant.contracts import CalculationContext, CalculationStatus
        from app.quant.scenarios import (
            OptionLeg,
            PositionDirection,
            ScenarioGrid,
            evaluate_leg_grid,
        )
        from app.portfolio_intelligence.contracts import ScenarioRow

        ctx = CalculationContext(reference_timestamp=REF, risk_free_rate=0.05)
        legs = (
            OptionLeg(option_type=Side.CALL, strike=24350.0, expiry=EXPIRY,
                      quantity=2.0, direction=PositionDirection.LONG,
                      entry_price=125.0, implied_volatility=0.2,
                      quality=QualityState.EXCELLENT, provenance=_prov("leg")),
            OptionLeg(option_type=Side.PUT, strike=24400.0, expiry=EXPIRY2,
                      quantity=1.0, direction=PositionDirection.SHORT,
                      entry_price=80.0, implied_volatility=0.2,
                      quality=QualityState.EXCELLENT, provenance=_prov("leg")),
        )
        grid = ScenarioGrid(spots=(24300.0, 24400.0),
                            times=(0.02,), ivs=(0.2,))
        rows = []
        for leg in legs:
            for point, qr in evaluate_leg_grid(leg, ctx, grid):
                if qr.status is not CalculationStatus.SUCCESS:
                    continue
                rows.append(ScenarioRow(
                    tenant_id="tenant-A",
                    point_id=f"{point.spot:g}",
                    spot=point.spot,
                    time_to_expiry=point.time_to_expiry,
                    implied_volatility=point.implied_volatility,
                    total_pnl=qr.values["pnl"],
                    partial=False,
                    quality=QualityState.EXCELLENT,
                    provenance=_prov("day18-grid"),
                ))

        # Feed the genuine Day-18 rows into the analytics boundary.
        positions = tuple(
            paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF)
            for row in self._paper_positions()
        )
        result = _analyze(positions, scenario_rows=tuple(rows))
        assert result.scenarios.state is EvidenceState.AVAILABLE
        assert result.scenarios.point_count == 4
        assert result.scenarios.complete_rows == 4
        # portfolio P/L at every point is genuinely computed by Day 18
        assert result.scenarios.worst_supplied_pnl is not None
        assert result.scenarios.worst_supplied_pnl < 0
        assert result.scenarios.best_supplied_pnl is not None

    def test_genuine_day23_regime_with_day35_views(self):
        from app.intelligence.contracts import MarketRegime, RegimeLabel

        regime = MarketRegime(label=RegimeLabel.RANGING, source="day23.regime",
                              model_version="2.1.0", reference_timestamp=REF)
        positions = tuple(
            paper_position_to_input(row, tenant_id="tenant-A",
                                    reference_timestamp=REF,
                                    greeks=_greeks(delta=0.5))
            for row in self._paper_positions()
        )
        result = _analyze(positions, regime=regime)
        assert result.regime_risk.regime is regime
        assert result.regime_risk.regime_label is RegimeLabel.RANGING
        # Descriptive only: delta context from measured evidence, no direction
        # manufactured from the label.
        assert result.regime_risk.net_delta_context == pytest.approx(0.5)
        assert result.status is PortfolioStatus.SUCCESS

    def test_genuine_paper_position_authority_never_replaced(self):
        """StrategyLegExposure attribution is NOT consumed as position truth:
        the analytics engine has no exposure table input surface at all."""
        import app.portfolio_intelligence.contracts as contracts

        # No attribution-table vocabulary exists in the analytics contracts.
        fields = {
            f for c in (
                contracts.PortfolioPosition,
                contracts.PortfolioExposure,
            ) for f in c.__dataclass_fields__
        }
        assert "strategy_leg_exposure" not in " ".join(fields).lower()
        assert "strategy_execution_id" not in " ".join(fields).lower()


# ---------------------------------------------------------------------------
# Purity: the domain modules never touch forbidden surfaces
# ---------------------------------------------------------------------------

_BANNED_MODULE_ROOTS = (
    "sqlalchemy", "fastapi", "requests", "httpx", "urllib", "socket",
    "subprocess", "redis", "os", "sys", "random", "secrets", "uuid",
    "pathlib", "datetime.now", "utcnow", "time.time", "brokers", "routers",
    "services", "db", "models", "central_risk",
)
#: Identifiers that would signal execution/decision authority leaking into the
#: analytics domain (docstrings and constant values may legitimately name the
#: boundaries they never cross; identifiers cannot).
_BANNED_IDENTIFIERS = frozenset({
    "execute", "execution", "order", "fill", "margin", "approval",
    "authorize", "authorization", "capital_allocation", "place_order",
})


def test_domain_modules_pure():
    root = Path(__file__).resolve().parents[1] / "app" / "portfolio_intelligence"
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 1. Import roots are restricted to shared pure foundations.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".")[0]
                    assert root_name not in _BANNED_MODULE_ROOTS, \
                        f"{path.name} imports banned module {alias.name!r}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_name = node.module.split(".")[0]
                assert root_name not in _BANNED_MODULE_ROOTS, \
                    f"{path.name} imports banned module {node.module!r}"
        # 2. No banned identifiers are bound or referenced.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in _BANNED_IDENTIFIERS, \
                    f"{path.name} uses banned identifier {node.id!r}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in _BANNED_IDENTIFIERS, \
                    f"{path.name} uses banned attribute {node.attr!r}"
        # 3. No wall-clock / random / uuid calls in source text.
        src = path.read_text(encoding="utf-8")
        for banned in ("datetime.now(", "utcnow(", "random.",
                       "secrets.", "uuid.", "time.time(", "monkeypatch"):
            assert banned not in src, f"{path.name} contains {banned!r}"


def test_package_exports():
    import app.portfolio_intelligence as pi

    assert hasattr(pi, "analyze_portfolio")
    assert hasattr(pi, "PortfolioAnalyticsResult")
    assert hasattr(pi, "PortfolioPosition")
    assert hasattr(pi, "paper_position_to_input")
    assert hasattr(pi, "broker_position_to_input")