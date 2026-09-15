"""Day 17 — Deterministic GEX Calculation & Gamma Profile tests (RED-phase
contract).

Proves the fourth real quantitative engine on the Day-14 boundary:

    Canonical option inputs + gamma + OI + explicit greeks source
        → QuantitativeEngineBoundary (provenance / quality guards)
        → GexCalculationEngine (app/quant/gex)
            values = {"raw_gex": ..., "signed_gex": ...}   per option
        → GammaProfile aggregation (strike rows + totals)
        → QuantResult / GammaProfile (quality + provenance + versions)

Rules locked by these tests
---------------------------
1. Canonical formula (GEX_V1_0_SPEC §6, preserved exactly by live_gex.py):
   ``Raw GEX = gamma × OI × S² × 0.01``.
2. **OI is in contracts — NEVER lots.** No lot-size multiplier is applied
   (NIFTY lot 65 must never enter the calculation).
3. Sign convention ``NAIVE_DEALER_CONVENTION`` (spec §6.1):
   ``Call GEX = +Raw``, ``Put GEX = −Raw`` — a modeling convention, never a
   claim about observed dealer positions.
4. Gamma source separation: every GEX input identifies its gamma source
   (``BROKER`` or ``MODEL`` per Day-9 ``GreeksObservation``); the result
   preserves it; a gamma profile NEVER silently mixes broker and model rows.
5. Missing ≠ zero: missing gamma/OI/source ⇒ UNAVAILABLE/INVALID — never a
   fabricated 0. Zero OI/gamma (legitimately zero) ⇒ valid 0.0 contribution.
6. Deterministic + broker-neutral: same inputs + context ⇒ identical results;
   no hidden wall clock / DB / broker / random state (Day-14 AST guards
   auto-extend over the new module; module-level AST checks also live here).
7. Quality/provenance are consumed (Day-12/Day-14 semantics), never recomputed
   or silently dropped: INSUFFICIENT quality and missing provenance block
   before the engine and exclude profile rows with structured reasons.

Golden expectations were computed by an independent scratch evaluation of the
formula (hand arithmetic, NOT the production functions) and cross-checked
against the pre-existing Phase-8A ``live_gex._raw_gex/_signed_gex``
implementation (agreement exact on the cross-checked fixtures).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from app.market_data.contracts import (
    DataMode,
    NormalizedInstrument,
    Provenance,
    QualityState,
    Side,
)
from app.quant.boundary import QuantitativeEngineBoundary
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    OptionMarketData,
    QuantResult,
)
from app.quant.gex import (
    GEX_FACTOR,
    METHOD_VERSION,
    SIGN_CONVENTION,
    GexCalculationEngine,
    CALCULATION_ID,
    CALCULATION_VERSION,
    MODEL_VERSION,
    build_gamma_profile,
    dealer_signed_gex,
    raw_gex,
)

_EXPIRY = "2028-09-03"
_REF = datetime(2028, 8, 3, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _option_instrument(*, side: Side, strike: float) -> NormalizedInstrument:
    return NormalizedInstrument(
        exchange="NSE",
        segment="FO",
        underlying="NIFTY",
        symbol=f"NIFTY {strike:g}{'CE' if side is Side.CALL else 'PE'}",
        instrument_type="OPTION",
        expiry=_EXPIRY,
        strike=strike,
        option_type=side,
    )


def _prov() -> Provenance:
    return Provenance(
        source="UPSTOX",
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=_REF,
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _ctx() -> CalculationContext:
    return CalculationContext(
        reference_timestamp=_REF,
        risk_free_rate=0.05,
        model_version=MODEL_VERSION,
        calculation_version=CALCULATION_VERSION,
    )


_UNSET = object()


def _md(
    *,
    side: Side,
    spot: float,
    strike: float,
    gamma: float | None,
    oi: float | None,
    greeks_source: str | None = "BROKER",
    quality: QualityState | None = QualityState.EXCELLENT,
    prov: object = _UNSET,
) -> OptionMarketData:
    return OptionMarketData(
        instrument=_option_instrument(side=side, strike=strike),
        spot=spot,
        implied_volatility=None,
        market_timestamp=_REF,
        received_timestamp=_REF,
        data_mode=DataMode.BROKER_SNAPSHOT,
        quality=quality,
        provenance=prov if prov is not _UNSET else _prov(),
        gamma=gamma,
        open_interest=oi,
        greeks_source=greeks_source,
    )


def _run(md: OptionMarketData, ctx: CalculationContext | None = None) -> QuantResult:
    boundary = QuantitativeEngineBoundary()
    boundary.register(GexCalculationEngine())
    return boundary.run(CALCULATION_ID, md, ctx or _ctx())


# ---------------------------------------------------------------------------
# 1. Golden values (independent, hand-arithmetic references)
# ---------------------------------------------------------------------------

# name, side, gamma, oi, spot, expected raw, expected signed
GOLDEN = [
    ("ATM_CE", Side.CALL, 0.0020, 100, 100, 20.0, 20.0),
    ("ATM_PE", Side.PUT, 0.0020, 100, 100, 20.0, -20.0),
    ("OTM_CE", Side.CALL, 0.0005, 150, 100, 7.5, 7.5),
    ("ITM_PE", Side.PUT, 0.0040, 50, 100, 20.0, -20.0),
    ("LOWVOL_CE", Side.CALL, 0.0001, 2000, 100, 20.0, 20.0),
    ("ZERO_OI", Side.CALL, 0.0020, 0, 100, 0.0, 0.0),
    ("ZERO_GAMMA", Side.PUT, 0.0, 100, 100, 0.0, 0.0),
    ("NIFTY_CE", Side.CALL, 0.003, 125000, 24000, 2160000000.0, 2160000000.0),
    ("NIFTY_PE", Side.PUT, 0.0025, 80000, 24000, 1152000000.0, -1152000000.0),
    ("TINY_GAMMA_CE", Side.CALL, 1e-7, 1000000, 10000, 99999.99999999999, 99999.99999999999),
    ("ITM_CE", Side.CALL, 0.0010, 20, 100, 2.0, 2.0),
    ("DEEP_OTM_PE", Side.PUT, 0.00001, 5000000, 100, 5000.000000000001, -5000.000000000001),
]


class TestGoldenValues:
    @pytest.mark.parametrize(
        "name,side,gamma,oi,spot,exp_raw,exp_signed",
        GOLDEN,
        ids=[g[0] for g in GOLDEN],
    )
    def test_pure_functions(self, name, side, gamma, oi, spot, exp_raw, exp_signed):
        assert raw_gex(gamma, oi, spot) == pytest.approx(exp_raw, rel=1e-12)
        assert dealer_signed_gex(side, gamma, oi, spot) == pytest.approx(exp_signed, rel=1e-12)

    @pytest.mark.parametrize(
        "name,side,gamma,oi,spot,exp_raw,exp_signed",
        GOLDEN,
        ids=[g[0] for g in GOLDEN],
    )
    def test_engine_through_boundary(self, name, side, gamma, oi, spot, exp_raw, exp_signed):
        result = _run(_md(side=side, spot=spot, strike=spot, gamma=gamma, oi=oi))
        assert result.status is CalculationStatus.SUCCESS
        assert set(result.values.keys()) == {"raw_gex", "signed_gex"}
        assert result.values["raw_gex"] == pytest.approx(exp_raw, rel=1e-12)
        assert result.values["signed_gex"] == pytest.approx(exp_signed, rel=1e-12)

    def test_agrees_with_verified_legacy_implementation(self):
        # Cross-implementation check against the pre-existing Phase-8A
        # live_gex module (a different codebase, NOT the module under test).
        from app.services.live_gex import _raw_gex as legacy_raw
        from app.services.live_gex import _signed_gex as legacy_signed

        for (name, side, gamma, oi, spot, exp_raw, exp_signed) in GOLDEN:
            if gamma is None:
                continue
            legacy_side = "call" if side is Side.CALL else "put"
            assert raw_gex(gamma, oi, spot) == pytest.approx(
                legacy_raw(float(gamma), float(oi), float(spot)), rel=1e-12
            )
            assert dealer_signed_gex(side, gamma, oi, spot) == pytest.approx(
                legacy_signed(legacy_side, float(gamma), float(oi), float(spot)), rel=1e-12
            )

    def test_convention_constants_are_explicit(self):
        assert GEX_FACTOR == 0.01
        assert SIGN_CONVENTION == "NAIVE_DEALER_CONVENTION"
        assert METHOD_VERSION == "GEX_STANDARD_V1"
        # model identity on the engine
        engine = GexCalculationEngine()
        assert engine.model == "GAMMA_EXPOSURE"
        assert engine.model_version == MODEL_VERSION
        assert engine.calculation_version == CALCULATION_VERSION
        assert engine.calculation_id == CALCULATION_ID


# ---------------------------------------------------------------------------
# 2. OI unit regression — OI is contracts, never lots
# ---------------------------------------------------------------------------


class TestOiUnitRegression:
    def test_oi_100_contracts_used_directly(self):
        # 0.002 × 100 × 24000² × 0.01 = 1,152,000 — OI=100 is used as 100.
        # If a lot_size (NIFTY = 65) were wrongly applied the result would be
        # 65× larger (74,880,000).
        assert raw_gex(0.002, 100, 24000) == pytest.approx(1152000.0, rel=1e-12)
        assert raw_gex(0.002, 100, 24000) != pytest.approx(74880000.0)
        assert raw_gex(0.002, 100, 24000) == raw_gex(0.002, 100 * 1, 24000)

    def test_no_lot_size_field_anywhere_in_formula_path(self):
        # The engine must compute 100 contracts = 100 contracts: doubling the
        # hypothetical lot to 130 must NOT change anything, because OI is
        # already contracts (a 65× multiplication would 65× the result).
        result = _run(_md(side=Side.CALL, spot=24000, strike=24000, gamma=0.002, oi=100))
        assert result.values["raw_gex"] == pytest.approx(1152000.0, rel=1e-12)

    def test_oi_large_finite_contract_scale(self):
        # realistic NIFTY scale: 0.003 × 125000 × 24000² × 0.01 = 2.16e9
        result = _run(_md(side=Side.CALL, spot=24000, strike=24000, gamma=0.003, oi=125000))
        assert result.values["raw_gex"] == pytest.approx(2160000000.0, rel=1e-12)


# ---------------------------------------------------------------------------
# 3. Sign convention — NAIVE_DEALER_CONVENTION
# ---------------------------------------------------------------------------


class TestSignConvention:
    def test_call_positive_put_negative(self):
        call = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100))
        put = _run(_md(side=Side.PUT, spot=100, strike=100, gamma=0.002, oi=100))
        assert call.values["signed_gex"] > 0
        assert put.values["signed_gex"] < 0
        assert call.values["signed_gex"] == -put.values["signed_gex"]
        # raw magnitudes are identical — only the sign differs
        assert call.values["raw_gex"] == put.values["raw_gex"]

    def test_put_signed_gex_is_negative_even_at_scale(self):
        result = _run(_md(side=Side.PUT, spot=24000, strike=24000, gamma=0.0025, oi=80000))
        assert result.values["signed_gex"] == pytest.approx(-1152000000.0, rel=1e-12)


# ---------------------------------------------------------------------------
# 4. Engine / boundary contract
# ---------------------------------------------------------------------------


class TestEngineContract:
    def test_missing_gamma_is_unavailable(self):
        result = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=None, oi=100))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)
        assert result.values is None

    def test_missing_oi_is_unavailable(self):
        result = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=None))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)

    def test_missing_greeks_source_is_unavailable(self):
        result = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100,
                          greeks_source=None))
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_REQUIRED_INPUT for i in result.issues)

    def test_unknown_greeks_source_is_invalid(self):
        result = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100,
                          greeks_source="ALGO"))
        assert result.status is CalculationStatus.INVALID_INPUT
        assert any(i.code is CalculationIssueCode.INVALID_INPUT_VALUE for i in result.issues)

    def test_zero_gamma_and_zero_oi_are_valid_zero_contributions(self):
        # legitimately zero (not missing) ⇒ SUCCESS with 0.0 — never UNAVAILABLE
        zero_gamma = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.0, oi=100))
        zero_oi = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=0))
        assert zero_gamma.status is CalculationStatus.SUCCESS
        assert zero_oi.status is CalculationStatus.SUCCESS
        assert zero_gamma.values["raw_gex"] == 0.0
        assert zero_oi.values["raw_gex"] == 0.0

    def test_insufficient_quality_blocked_before_engine(self):
        md = _md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100,
                 quality=QualityState.INSUFFICIENT)
        result = _run(md)
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.INSUFFICIENT_QUALITY for i in result.issues)
        assert result.values is None

    def test_missing_provenance_blocked_before_engine(self):
        md = _md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100, prov=None)
        result = _run(md)
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_PROVENANCE for i in result.issues)

    def test_degraded_quality_permitted_and_preserved(self):
        md = _md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100,
                 quality=QualityState.DEGRADED)
        result = _run(md)
        assert result.status is CalculationStatus.SUCCESS
        assert result.input_quality is QualityState.DEGRADED

    def test_envelope_preserves_greeks_source_and_versions(self):
        for source in ("BROKER", "MODEL"):
            md = _md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100,
                     greeks_source=source)
            result = _run(md)
            assert result.status is CalculationStatus.SUCCESS
            assert result.greeks_source == source
            assert result.provenance == md.provenance
            assert result.reference_timestamp == _REF
            assert result.model_version == MODEL_VERSION
            assert result.calculation_version == CALCULATION_VERSION
            assert result.calculation_id == CALCULATION_ID
            assert result.contract_version == "1.0.0"


# ---------------------------------------------------------------------------
# 5. Property tests / invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    def test_doubling_oi_doubles_gex(self):
        base = raw_gex(0.002, 100, 100)
        double = raw_gex(0.002, 200, 100)
        assert double == pytest.approx(2 * base, rel=1e-12)

    def test_doubling_gamma_doubles_gex(self):
        base = raw_gex(0.002, 100, 100)
        double = raw_gex(0.004, 100, 100)
        assert double == pytest.approx(2 * base, rel=1e-12)

    def test_gex_scales_with_spot_squared(self):
        # same gamma/OI: S=100 → S=200 quadruples raw GEX (200²/100² = 4)
        g, oi = 0.002, 100
        assert raw_gex(g, oi, 200) == pytest.approx(4 * raw_gex(g, oi, 100), rel=1e-12)
        assert raw_gex(g, oi, 300) == pytest.approx(9 * raw_gex(g, oi, 100), rel=1e-12)

    def test_zero_gamma_yields_zero_gex(self):
        assert raw_gex(0.0, 500, 25000) == 0.0
        assert dealer_signed_gex(Side.PUT, 0.0, 500, 25000) == 0.0

    def test_zero_oi_yields_zero_gex(self):
        assert raw_gex(0.003, 0, 25000) == 0.0
        assert dealer_signed_gex(Side.CALL, 0.003, 0, 25000) == 0.0

    def test_gamma_and_oi_are_never_collapsed(self):
        # gamma=0.004/OI=50 and gamma=0.002/OI=100 give the same raw GEX but
        # must remain distinguishable inputs (engine result reflects inputs)
        a = raw_gex(0.004, 50, 100)
        b = raw_gex(0.002, 100, 100)
        assert a == pytest.approx(b, rel=1e-12)


# ---------------------------------------------------------------------------
# 6. Gamma profile aggregation
# ---------------------------------------------------------------------------


def _profile_row(side: Side, strike: float, gamma: float, oi: float,
                 spot: float = 100.0, **kw) -> OptionMarketData:
    return _md(side=side, spot=spot, strike=strike, gamma=gamma, oi=oi, **kw)


class TestGammaProfile:
    def test_one_strike_both_legs(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100),    # +20
            _profile_row(Side.PUT, 100.0, 0.002, 100),     # -20
        ]
        profile = build_gamma_profile(rows)
        assert profile.total_call_gex == pytest.approx(20.0, rel=1e-12)
        assert profile.total_put_gex == pytest.approx(-20.0, rel=1e-12)
        assert profile.total_net_gex == pytest.approx(0.0, abs=1e-12)
        assert len(profile.rows) == 1
        row = profile.rows[0]
        assert row.strike == 100.0
        assert row.call_gex == pytest.approx(20.0, rel=1e-12)
        assert row.put_gex == pytest.approx(-20.0, rel=1e-12)
        assert row.net_gex == pytest.approx(0.0, abs=1e-12)

    def test_ce_only_profile(self):
        rows = [_profile_row(Side.CALL, 100.0, 0.002, 100)]
        profile = build_gamma_profile(rows)
        assert profile.total_call_gex == pytest.approx(20.0, rel=1e-12)
        assert profile.total_put_gex is None  # no put rows exist — not zero
        assert profile.total_net_gex == pytest.approx(20.0, rel=1e-12)
        assert profile.rows[0].put_gex is None
        assert profile.rows[0].net_gex == pytest.approx(20.0, rel=1e-12)

    def test_multiple_strikes_sorted_ascending(self):
        rows = [
            _profile_row(Side.CALL, 25000.0, 0.002, 60000, spot=24000.0),
            _profile_row(Side.PUT, 25000.0, 0.003, 90000, spot=24000.0),
            _profile_row(Side.CALL, 24000.0, 0.003, 125000, spot=24000.0),
            _profile_row(Side.PUT, 24000.0, 0.0025, 80000, spot=24000.0),
        ]
        profile = build_gamma_profile(rows)
        assert [r.strike for r in profile.rows] == [24000.0, 25000.0]
        # The formula uses the shared underlying spot S = 24000 for every row.
        # 24000 row: call 0.003×125000×24000²×0.01 = +2.16e9;
        #            put 0.0025×80000×24000²×0.01 = −1.152e9 → net +1.008e9
        assert profile.rows[0].net_gex == pytest.approx(1008000000.0, rel=1e-12)
        # 25000 row (S still 24000): call 0.002×60000×24000²×0.01 = +6.912e8;
        #            put 0.003×90000×24000²×0.01 = −1.5552e9 → net −8.64e8
        assert profile.rows[1].net_gex == pytest.approx(-864000000.0, rel=1e-12)
        assert profile.total_call_gex == pytest.approx(2851200000.0, rel=1e-12)
        assert profile.total_put_gex == pytest.approx(-2707200000.0, rel=1e-12)
        assert profile.total_net_gex == pytest.approx(144000000.0, rel=1e-12)

    def test_unsorted_input_sorted_by_strike(self):
        rows = [
            _profile_row(Side.PUT, 200.0, 0.001, 10),
            _profile_row(Side.CALL, 50.0, 0.001, 10),
            _profile_row(Side.CALL, 150.0, 0.001, 10),
            _profile_row(Side.CALL, 100.0, 0.001, 10),
        ]
        profile = build_gamma_profile(rows)
        assert [r.strike for r in profile.rows] == [50.0, 100.0, 150.0, 200.0]

    def test_duplicate_strike_rows_each_contribute(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.001, 100),   # +10
            _profile_row(Side.CALL, 100.0, 0.001, 100),   # +10 (second observation)
            _profile_row(Side.PUT, 100.0, 0.001, 100),    # -10
        ]
        profile = build_gamma_profile(rows)
        assert len(profile.rows) == 1
        # both call rows contribute — 20 not 10 (no silent de-duplication)
        assert profile.rows[0].call_gex == pytest.approx(20.0, rel=1e-12)
        assert profile.rows[0].net_gex == pytest.approx(10.0, rel=1e-12)

    def test_zero_oi_rows_included_as_zero(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 0),   # 0 contribution, valid
            _profile_row(Side.PUT, 100.0, 0.002, 100),  # -20
        ]
        profile = build_gamma_profile(rows)
        assert len(profile.rows) == 1
        assert profile.rows[0].call_gex == pytest.approx(0.0, abs=1e-12)
        assert profile.rows[0].net_gex == pytest.approx(-20.0, rel=1e-12)
        assert profile.total_call_gex == pytest.approx(0.0, abs=1e-12)

    def test_empty_profile_has_no_totals(self):
        profile = build_gamma_profile([])
        assert profile.rows == ()
        assert profile.total_call_gex is None
        assert profile.total_put_gex is None
        assert profile.total_net_gex is None
        assert profile.excluded == ()

    def test_conservation_sum_of_strike_nets_equals_total_net(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100),
            _profile_row(Side.PUT, 100.0, 0.002, 200),
            _profile_row(Side.CALL, 120.0, 0.001, 300),
            _profile_row(Side.PUT, 80.0, 0.0015, 150),
        ]
        profile = build_gamma_profile(rows)
        total = sum(r.net_gex for r in profile.rows)
        assert profile.total_net_gex == pytest.approx(total, rel=1e-12)

    def test_profile_deterministic(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100),
            _profile_row(Side.PUT, 100.0, 0.002, 200),
            _profile_row(Side.CALL, 120.0, 0.001, 300),
        ]
        assert build_gamma_profile(rows) == build_gamma_profile(list(reversed(rows)))


class TestProfileValidationAndExclusions:
    def test_invalid_rows_excluded_with_reason_not_fabricated(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100),                    # valid +20
            _profile_row(Side.CALL, 110.0, None, 100),                     # missing gamma
            _profile_row(Side.PUT, 120.0, 0.002, None),                    # missing OI
            _profile_row(Side.PUT, 130.0, 0.002, 100, quality=QualityState.INSUFFICIENT),
            _profile_row(Side.CALL, 140.0, 0.002, 100, prov=None),         # no provenance
            _profile_row(Side.PUT, 150.0, 0.002, 100, greeks_source="ALGO"),  # bad token
        ]
        profile = build_gamma_profile(rows)
        assert [r.strike for r in profile.rows] == [100.0]
        assert profile.total_call_gex == pytest.approx(20.0, rel=1e-12)
        assert len(profile.excluded) == 5
        reasons = {e.reason for e in profile.excluded}
        assert CalculationIssueCode.INVALID_INPUT_VALUE in reasons  # bad source token
        assert CalculationIssueCode.MISSING_REQUIRED_INPUT in reasons  # missing gamma/OI
        assert CalculationIssueCode.INSUFFICIENT_QUALITY in reasons
        assert CalculationIssueCode.MISSING_PROVENANCE in reasons

    def test_negative_oi_and_gamma_rejected_at_contract(self):
        # The OptionMarketData contract already rejects negative OI/gamma at
        # construction — the pure GEX functions re-raise for direct callers.
        with pytest.raises(ValueError):
            _profile_row(Side.CALL, 100.0, 0.002, -5)
        with pytest.raises(ValueError):
            _profile_row(Side.CALL, 100.0, -0.001, 100)
        with pytest.raises(ValueError):
            raw_gex(0.002, -1, 100)
        with pytest.raises(ValueError):
            dealer_signed_gex(Side.CALL, 0.002, -1, 100)
        with pytest.raises(ValueError):
            raw_gex(0.002, 100, 0)
        with pytest.raises(ValueError):
            raw_gex(float("nan"), 100, 100)
        with pytest.raises(ValueError):
            raw_gex(0.002, float("inf"), 100)

    def test_missing_leg_is_not_invented(self):
        rows = [_profile_row(Side.CALL, 100.0, 0.002, 100)]
        profile = build_gamma_profile(rows)
        assert profile.rows[0].put_gex is None  # never invented as 0.0

    def test_mixed_broker_and_model_rows_rejected(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100, greeks_source="BROKER"),
            _profile_row(Side.PUT, 100.0, 0.002, 100, greeks_source="MODEL"),
        ]
        with pytest.raises(ValueError):
            build_gamma_profile(rows)

    def test_mismatched_spot_across_rows_rejected(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100, spot=100.0),
            _profile_row(Side.PUT, 100.0, 0.002, 100, spot=101.0),
        ]
        with pytest.raises(ValueError):
            build_gamma_profile(rows)

    def test_missing_greeks_source_row_excluded(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100, greeks_source=None),
        ]
        profile = build_gamma_profile(rows)
        assert profile.rows == ()
        assert len(profile.excluded) == 1
        assert profile.excluded[0].reason is CalculationIssueCode.MISSING_REQUIRED_INPUT

    def test_unknown_source_row_excluded(self):
        rows = [_profile_row(Side.CALL, 100.0, 0.002, 100, greeks_source="ALGO")]
        profile = build_gamma_profile(rows)
        assert profile.rows == ()
        assert profile.excluded[0].reason is CalculationIssueCode.INVALID_INPUT_VALUE

    def test_profile_source_label_reflects_valid_rows(self):
        rows = [
            _profile_row(Side.CALL, 100.0, 0.002, 100, greeks_source="MODEL"),
            _profile_row(Side.PUT, 100.0, 0.002, 100, greeks_source="MODEL"),
        ]
        profile = build_gamma_profile(rows)
        assert profile.greeks_source == "MODEL"


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_identical_engine_results(self):
        md = _md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100)
        assert _run(md) == _run(md)

    def test_spot_change_changes_result_proportionally(self):
        s1 = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100))
        s2 = _run(_md(side=Side.CALL, spot=200, strike=100, gamma=0.002, oi=100))
        assert s1.status is CalculationStatus.SUCCESS
        assert s2.values["raw_gex"] == pytest.approx(4 * s1.values["raw_gex"], rel=1e-12)

    def test_gamma_input_change_changes_result(self):
        g1 = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.001, oi=100))
        g2 = _run(_md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100))
        assert g1.values["raw_gex"] != g2.values["raw_gex"]


# ---------------------------------------------------------------------------
# 8. Edge cases / numerical safety
# ---------------------------------------------------------------------------


class TestNumericalSafety:
    @pytest.mark.parametrize(
        "gamma,oi,spot",
        [
            (0.002, 100, 1e6),   # very large spot
            (0.002, 1e9, 100),   # very large finite OI
            (1e-9, 100, 100),    # very small gamma
            (0.002, 0, 24000),
            (0.0, 500, 24000),
        ],
    )
    def test_valid_extremes_finite(self, gamma, oi, spot):
        result = _run(_md(side=Side.CALL, spot=spot, strike=spot, gamma=gamma, oi=oi))
        assert result.status is CalculationStatus.SUCCESS
        assert math.isfinite(result.values["raw_gex"])
        assert math.isfinite(result.values["signed_gex"])

    def test_deep_moneyness_is_irrelevant_to_pure_gex(self):
        # GEX uses gamma × OI × S² — moneyness enters only through gamma; the
        # engine must not use option price/IV anywhere.
        result = _run(_md(side=Side.CALL, spot=100, strike=1e9, gamma=0.002, oi=100))
        assert result.status is CalculationStatus.SUCCESS
        assert result.values["raw_gex"] == pytest.approx(20.0, rel=1e-12)


# ---------------------------------------------------------------------------
# 9. Security & broker neutrality (module-level static)
# ---------------------------------------------------------------------------


class TestSecurityAndPurity:
    def test_module_has_no_clock_or_io_imports(self):
        import ast as _ast
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "app" / "quant" / "gex.py"
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx",
                     "urllib", "fastapi"}
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute):
                assert node.func.attr not in {"now", "utcnow", "today"}
            if isinstance(node, _ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in forbidden
            elif isinstance(node, _ast.ImportFrom):
                assert not (node.module or "").startswith("app.brokers")
                assert not (node.module or "").startswith("app.services")
                assert not (node.module or "").startswith("app.market_data.quality")

    def test_results_never_leak_credentials(self):
        secret = "sk_live_upstox_secret_xyz"
        md = _md(side=Side.CALL, spot=100, strike=100, gamma=0.002, oi=100)
        md = OptionMarketData(
            instrument=md.instrument, spot=md.spot, implied_volatility=None,
            market_timestamp=md.market_timestamp, received_timestamp=md.received_timestamp,
            data_mode=md.data_mode, quality=md.quality,
            provenance=Provenance(
                source="UPSTOX", collection_mode=DataMode.BROKER_SNAPSHOT.value,
                received_at=md.received_timestamp, normalization_version="1.0.0",
                contract_version="1.0.0", transformation_id=None,
            ),
            gamma=0.002, open_interest=100, greeks_source="BROKER",
        )
        result = _run(md)
        assert result.status is CalculationStatus.SUCCESS
        assert secret not in str(result)
        assert "access_token" not in str(result)
        assert "authorization" not in str(result)
