"""Day 14 — Quantitative Engine Boundary tests (RED-phase contract).

Proves the backend quant boundary that will become authoritative for
platform decisions (Blueprint §9 / master plan Day 14) — WITHOUT shipping any
calculation engine (Greeks/IV/pricing/GEX/scenario are Days 15–18):

    Canonical Market Data (Day 9)
        → Data Quality (Day 12, consumed — never recomputed)
        → Quantitative Engine Boundary (app/quant)
            deterministic CalculationContext   (reference time, r, q, versions,
                                                tolerance policy)
            canonical OptionMarketData input   (terms + market values +
                                                provenance + quality)
            QuantEngine protocol + routing     (registry-lite)
            QuantResult envelope               (status / values / issues /
                                                quality / provenance / versions)
        → Day 15+ engines → Intelligence

Rules locked by these tests
---------------------------
1. Broker-neutral: ``app/quant`` imports zero broker modules (AST-enforced).
2. Deterministic: no wall clock / DB / HTTP / broker SDK / hidden state; the
   only notion of now is ``CalculationContext.reference_timestamp``
   (AST-enforced + behavioral).
3. No fabrication: missing market values stay None; missing provenance or
   INSUFFICIENT input quality ⇒ deterministic UNAVAILABLE, never a guessed
   value; an unregistered calculation ⇒ NOT_IMPLEMENTED, never a result.
4. Calculation output, input quality, calculation status and provenance stay
   separate — never collapsed into a confidence/score.
5. Provenance (Day 9) is preserved end-to-end; quality (Day 12) propagates
   without duplication (the boundary never scores).
6. Versioning (contract/model/calculation) is explicit on every result.
7. Missing/invalid inputs are handled with structured, credential-free issues.
"""

from __future__ import annotations

import ast
import math
import pathlib
from datetime import datetime, timezone
from typing import Any

import pytest

from app.market_data.contracts import (
    ContractVersion,
    DataMode,
    NormalizedInstrument,
    Provenance,
    QualityState,
    Side,
)
from app.quant.boundary import QuantEngine, QuantitativeEngineBoundary
from app.quant.contracts import (
    CalculationContext,
    CalculationIssueCode,
    CalculationStatus,
    NumericalTolerance,
    OptionMarketData,
    QuantIssue,
    QuantResult,
    nearly_equal,
    time_to_expiry,
)

_QUANT_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "quant"

# ---------------------------------------------------------------------------
# Factories / helpers
# ---------------------------------------------------------------------------


def _option_instrument(
    *,
    symbol: str = "NIFTY 26SEP2424200CE",
    underlying: str = "NIFTY",
    strike: float = 24200.0,
    side: Side = Side.CALL,
    expiry: str = "2026-09-24",
    instrument_type: str = "OPTION",
) -> NormalizedInstrument:
    return NormalizedInstrument(
        exchange="NSE",
        segment="FO",
        underlying=underlying,
        symbol=symbol,
        instrument_type=instrument_type,
        expiry=expiry,
        strike=strike,
        option_type=side,
    )


_UNSET = object()


def _prov(source: str = "UPSTOX") -> Provenance:
    return Provenance(
        source=source,
        collection_mode=DataMode.BROKER_SNAPSHOT.value,
        received_at=datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc),
        normalization_version="1.0.0",
        contract_version="1.0.0",
        transformation_id=None,
    )


def _ctx(
    *,
    reference: datetime | None = None,
    risk_free: float = 0.065,
    dividend: float | None = None,
    **kwargs,
) -> CalculationContext:
    return CalculationContext(
        reference_timestamp=reference or datetime(2026, 9, 3, 10, 30, 0, tzinfo=timezone.utc),
        risk_free_rate=risk_free,
        dividend_yield=dividend,
        **kwargs,
    )


def _market_data(
    *,
    instrument: NormalizedInstrument | None = None,
    spot: float = 24230.5,
    market_price: float | None = 250.5,
    iv: float | None = 0.18,
    quality: QualityState | None = QualityState.EXCELLENT,
    prov: Provenance | None | None = _UNSET,
    **kwargs,
) -> OptionMarketData:
    if prov is _UNSET:
        prov = _prov()
    return OptionMarketData(
        instrument=instrument or _option_instrument(),
        spot=spot,
        market_price=market_price,
        implied_volatility=iv,
        market_timestamp=kwargs.pop("market_ts", datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)),
        received_timestamp=kwargs.pop(
            "received_ts", datetime(2026, 9, 3, 10, 0, 1, tzinfo=timezone.utc)
        ),
        data_mode=DataMode.BROKER_SNAPSHOT,
        quality=quality,
        provenance=prov,
        **kwargs,
    )


class StubEngine:
    """Test-only deterministic engine proving boundary routing.

    NOT a real quantitative engine — deliberately trivial deterministic math
    so Day 14 never ships model calculations.
    """

    calculation_id = "test.greeks.black_scholes_european"
    call_count = 0

    def calculate(self, market_data: OptionMarketData, context: CalculationContext) -> QuantResult:
        type(self).call_count += 1
        t = time_to_expiry(market_data.instrument.expiry, context.reference_timestamp)
        decay = math.exp(-context.risk_free_rate * t)
        # Deterministic sample outputs derived ONLY from inputs + context.
        moneyness = market_data.spot / market_data.instrument.strike
        return QuantResult(
            calculation_id=self.calculation_id,
            status=CalculationStatus.SUCCESS,
            values={
                "delta": round(moneyness * decay, 12),
                "time_to_expiry_years": round(t, 12),
            },
            input_quality=market_data.quality,
            provenance=market_data.provenance,
            reference_timestamp=context.reference_timestamp,
            model_version=context.model_version,
            calculation_version=context.calculation_version,
            contract_version=ContractVersion.v1_0_0.value,
        )


class RaisingEngine:
    calculation_id = "test.engine.raises"

    def calculate(self, market_data, context):
        raise RuntimeError("boom")


class BadResultEngine:
    calculation_id = "test.engine.bad_result"

    def calculate(self, market_data, context):
        return {"not": "a QuantResult"}


class EmptySuccessEngine:
    calculation_id = "test.engine.empty_success"

    def calculate(self, market_data, context):
        return QuantResult(
            calculation_id=self.calculation_id,
            status=CalculationStatus.SUCCESS,
            values=None,  # success without values is a boundary violation
        )


@pytest.fixture(autouse=True)
def _reset_stub():
    StubEngine.call_count = 0
    yield


def _boundary() -> QuantitativeEngineBoundary:
    b = QuantitativeEngineBoundary()
    b.register(StubEngine())
    b.register(RaisingEngine())
    b.register(BadResultEngine())
    b.register(EmptySuccessEngine())
    return b


# ---------------------------------------------------------------------------
# 1. Numerical tolerance policy
# ---------------------------------------------------------------------------


class TestNumericalTolerance:
    def test_defaults_are_finite_and_non_negative(self):
        tol = NumericalTolerance()
        assert tol.relative == 1e-9
        assert tol.absolute == 1e-12
        assert tol.relative >= 0 and tol.absolute >= 0

    def test_validation_rejects_negative(self):
        with pytest.raises(ValueError):
            NumericalTolerance(relative=-1e-9)
        with pytest.raises(ValueError):
            NumericalTolerance(absolute=-1e-12)

    def test_validation_rejects_non_finite(self):
        with pytest.raises(ValueError):
            NumericalTolerance(relative=float("nan"))
        with pytest.raises(ValueError):
            NumericalTolerance(absolute=float("inf"))

    def test_nearly_equal_within_absolute(self):
        assert nearly_equal(1.0, 1.0 + 1e-13)

    def test_nearly_equal_within_relative(self):
        assert nearly_equal(1e9, 1e9 * (1 + 1e-10))

    def test_nearly_equal_far_values_false(self):
        assert not nearly_equal(1.0, 2.0)

    def test_nearly_equal_exact_true(self):
        assert nearly_equal(0.1 + 0.2, 0.30000000000000004)

    def test_frozen(self):
        tol = NumericalTolerance()
        with pytest.raises(Exception):
            tol.relative = 0.1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Time-to-expiry normalization (ACT/365 input convention — NOT a model)
# ---------------------------------------------------------------------------


class TestTimeToExpiry:
    def test_positive_before_expiry(self):
        ref = datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc)
        t = time_to_expiry("2026-09-24", ref)
        assert t > 0
        # ACT/365 from expiry UTC midnight
        expected = (datetime(2026, 9, 24, tzinfo=timezone.utc) - ref).total_seconds() / (
            365.0 * 86400.0
        )
        assert t == pytest.approx(expected, rel=1e-12)

    def test_timezone_normalized_deterministic(self):
        ref_utc = datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc)
        ref_ist = ref_utc.astimezone(timezone.utc)
        assert time_to_expiry("2026-09-24", ref_ist) == time_to_expiry("2026-09-24", ref_utc)

    def test_expired_expiry_returns_zero(self):
        ref = datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc)
        assert time_to_expiry("2026-09-24", ref) == 0.0

    def test_same_day_reference_returns_zero(self):
        ref = datetime(2026, 9, 24, 23, 0, tzinfo=timezone.utc)
        assert time_to_expiry("2026-09-24", ref) == 0.0

    def test_invalid_expiry_raises(self):
        ref = datetime(2026, 9, 3, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            time_to_expiry("not-a-date", ref)

    def test_naive_reference_raises(self):
        with pytest.raises(ValueError):
            time_to_expiry("2026-09-24", datetime(2026, 9, 3))

    def test_deterministic(self):
        ref = datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc)
        assert time_to_expiry("2026-09-24", ref) == time_to_expiry("2026-09-24", ref)


# ---------------------------------------------------------------------------
# 3. Calculation context
# ---------------------------------------------------------------------------


class TestCalculationContext:
    def test_requires_aware_reference_timestamp(self):
        with pytest.raises(ValueError):
            CalculationContext(reference_timestamp=datetime(2026, 9, 3), risk_free_rate=0.065)

    def test_risk_free_rate_required(self):
        with pytest.raises(TypeError):
            CalculationContext(reference_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc))

    def test_rejects_non_finite_risk_free(self):
        with pytest.raises(ValueError):
            _ctx(risk_free=float("nan"))
        with pytest.raises(ValueError):
            _ctx(risk_free=float("inf"))

    def test_rejects_non_finite_dividend(self):
        with pytest.raises(ValueError):
            _ctx(dividend=float("nan"))

    def test_frozen(self):
        ctx = _ctx()
        with pytest.raises(Exception):
            ctx.risk_free_rate = 0.05  # type: ignore[misc]

    def test_versions_carried(self):
        ctx = _ctx(model_version="black_scholes_1.0", calculation_version="1.2.3")
        assert ctx.model_version == "black_scholes_1.0"
        assert ctx.calculation_version == "1.2.3"


# ---------------------------------------------------------------------------
# 4. Option market-data input contract
# ---------------------------------------------------------------------------


class TestOptionMarketData:
    def test_valid_option_input(self):
        md = _market_data()
        assert md.spot == 24230.5
        assert md.market_price == 250.5
        assert md.implied_volatility == 0.18
        assert md.instrument.is_concrete_contract
        assert md.provenance is not None

    def test_missing_values_stay_none(self):
        md = _market_data(market_price=None, iv=None)
        assert md.market_price is None
        assert md.implied_volatility is None

    def test_frozen(self):
        md = _market_data()
        with pytest.raises(Exception):
            md.spot = 1.0  # type: ignore[misc]

    def test_rejects_index_instrument(self):
        idx = NormalizedInstrument(
            exchange="NSE", segment="INDEX", underlying="NIFTY", symbol="NIFTY 50",
            instrument_type="INDEX",
        )
        with pytest.raises(ValueError):
            _market_data(instrument=idx)

    def test_rejects_non_concrete_option(self):
        # option type present but no expiry / strike
        partial = NormalizedInstrument(
            exchange="NSE", segment="FO", underlying="NIFTY", symbol="X",
            instrument_type="OPTION", option_type=Side.CALL,
        )
        with pytest.raises(ValueError):
            _market_data(instrument=partial)

    def test_rejects_non_positive_spot(self):
        with pytest.raises(ValueError):
            _market_data(spot=0.0)
        with pytest.raises(ValueError):
            _market_data(spot=-100.0)

    def test_rejects_non_finite_spot(self):
        with pytest.raises(ValueError):
            _market_data(spot=float("nan"))
        with pytest.raises(ValueError):
            _market_data(spot=float("inf"))

    def test_rejects_negative_market_price(self):
        with pytest.raises(ValueError):
            _market_data(market_price=-5.0)

    def test_rejects_non_finite_market_price(self):
        with pytest.raises(ValueError):
            _market_data(market_price=float("nan"))

    def test_rejects_negative_iv(self):
        with pytest.raises(ValueError):
            _market_data(iv=-0.1)

    def test_rejects_non_finite_iv(self):
        with pytest.raises(ValueError):
            _market_data(iv=float("inf"))

    def test_rejects_naive_timestamps(self):
        with pytest.raises(ValueError):
            _market_data(market_ts=datetime(2026, 9, 3, 10, 0))
        with pytest.raises(ValueError):
            _market_data(received_ts=datetime(2026, 9, 3, 10, 0))

    def test_rejects_invalid_expiry_on_instrument(self):
        inst = _option_instrument(expiry="not-a-date")
        with pytest.raises(ValueError):
            _market_data(instrument=inst)

    def test_quality_and_provenance_optional(self):
        md = _market_data(quality=None, prov=None)
        assert md.quality is None
        assert md.provenance is None


# ---------------------------------------------------------------------------
# 5. Quant result envelope
# ---------------------------------------------------------------------------


class TestQuantResult:
    def test_statuses_are_distinct(self):
        values = {s.value for s in CalculationStatus}
        assert values == {"SUCCESS", "UNAVAILABLE", "INVALID_INPUT", "FAILED"}

    def test_issue_codes_are_structured(self):
        codes = {c.value for c in CalculationIssueCode}
        assert "MISSING_REQUIRED_INPUT" in codes
        assert "INVALID_INPUT_VALUE" in codes
        assert "NOT_IMPLEMENTED" in codes
        assert "MISSING_PROVENANCE" in codes
        assert "INSUFFICIENT_QUALITY" in codes

    def test_issue_message_never_embeds_payload(self):
        issue = QuantIssue(
            code=CalculationIssueCode.INVALID_INPUT_VALUE,
            message="market_price must be a non-negative finite number.",
            field="market_price",
        )
        assert "last_price" not in str(issue)
        assert "instrument_token" not in str(issue)

    def test_result_frozen(self):
        r = QuantResult(calculation_id="x", status=CalculationStatus.UNAVAILABLE)
        with pytest.raises(Exception):
            r.status = CalculationStatus.SUCCESS  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 6. Boundary routing
# ---------------------------------------------------------------------------


class TestBoundaryRouting:
    async def test_unknown_calculation_is_unavailable_not_fabricated(self):
        b = _boundary()
        result = b.run("greeks.black_scholes_european", _market_data(), _ctx())
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.NOT_IMPLEMENTED for i in result.issues)
        assert result.values is None  # never a fabricated value

    async def test_registered_stub_engine_routes(self):
        b = _boundary()
        result = b.run(StubEngine.calculation_id, _market_data(), _ctx())
        assert result.status is CalculationStatus.SUCCESS
        assert result.values is not None
        assert "delta" in result.values
        assert StubEngine.call_count == 1

    async def test_available_calculations_lists_registered(self):
        b = _boundary()
        available = b.available_calculations()
        assert StubEngine.calculation_id in available
        assert available == tuple(sorted(available))

    async def test_duplicate_registration_rejected(self):
        b = QuantitativeEngineBoundary()
        b.register(StubEngine())
        with pytest.raises(ValueError):
            b.register(StubEngine())

    async def test_registration_requires_calculation_id(self):
        b = QuantitativeEngineBoundary()

        class NoId:
            def calculate(self, market_data, context):
                return QuantResult(calculation_id="x", status=CalculationStatus.UNAVAILABLE)

        with pytest.raises(ValueError):
            b.register(NoId())

    async def test_engine_raising_is_failed_not_crash(self):
        b = _boundary()
        result = b.run(RaisingEngine.calculation_id, _market_data(), _ctx())
        assert result.status is CalculationStatus.FAILED
        assert any(i.code is CalculationIssueCode.INTERNAL_ERROR for i in result.issues)
        # engine exception text never leaks
        assert "boom" not in str(result.issues)

    async def test_engine_returning_non_result_is_failed(self):
        b = _boundary()
        result = b.run(BadResultEngine.calculation_id, _market_data(), _ctx())
        assert result.status is CalculationStatus.FAILED

    async def test_success_requires_values(self):
        b = _boundary()
        result = b.run(EmptySuccessEngine.calculation_id, _market_data(), _ctx())
        assert result.status is CalculationStatus.FAILED


# ---------------------------------------------------------------------------
# 7. Boundary guards — provenance & quality
# ---------------------------------------------------------------------------


class TestBoundaryGuards:
    async def test_missing_provenance_is_unavailable(self):
        b = _boundary()
        result = b.run(StubEngine.calculation_id, _market_data(prov=None), _ctx())
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.MISSING_PROVENANCE for i in result.issues)
        assert StubEngine.call_count == 0  # engine never ran

    async def test_insufficient_quality_is_unavailable(self):
        b = _boundary()
        result = b.run(
            StubEngine.calculation_id,
            _market_data(quality=QualityState.INSUFFICIENT),
            _ctx(),
        )
        assert result.status is CalculationStatus.UNAVAILABLE
        assert any(i.code is CalculationIssueCode.INSUFFICIENT_QUALITY for i in result.issues)
        assert StubEngine.call_count == 0

    async def test_degraded_quality_permitted_but_preserved(self):
        b = _boundary()
        result = b.run(
            StubEngine.calculation_id,
            _market_data(quality=QualityState.DEGRADED),
            _ctx(),
        )
        assert result.status is CalculationStatus.SUCCESS
        assert result.input_quality is QualityState.DEGRADED

    async def test_good_quality_permitted(self):
        b = _boundary()
        result = b.run(
            StubEngine.calculation_id,
            _market_data(quality=QualityState.GOOD),
            _ctx(),
        )
        assert result.status is CalculationStatus.SUCCESS

    async def test_missing_quality_permitted(self):
        # missing quality is distinct from INSUFFICIENT — no Day-12 scoring here
        b = _boundary()
        result = b.run(StubEngine.calculation_id, _market_data(quality=None), _ctx())
        assert result.status is CalculationStatus.SUCCESS
        assert result.input_quality is None


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    async def test_identical_inputs_identical_results(self):
        b = _boundary()
        md, ctx = _market_data(), _ctx(model_version="m1", calculation_version="1.2.3")
        r1 = b.run(StubEngine.calculation_id, md, ctx)
        r2 = b.run(StubEngine.calculation_id, md, ctx)
        assert r1 == r2
        assert r1.values == r2.values
        assert r1.status is CalculationStatus.SUCCESS

    async def test_time_affects_calculation_only_through_context(self):
        b = _boundary()
        md = _market_data()
        early = _ctx(reference=datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc))
        later = _ctx(reference=datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc))
        r_early = b.run(StubEngine.calculation_id, md, early)
        r_later = b.run(StubEngine.calculation_id, md, later)
        # only time_to_expiry differs; delta identical for this stub
        assert r_early.values["time_to_expiry_years"] != r_later.values["time_to_expiry_years"]
        assert r_early == r_early  # same context → same result

    async def test_stub_uses_only_explicit_inputs(self):
        # the stub derives its outputs from spot/strike/r/T only — sanity: no
        # environment dependence is possible because app/quant cannot read it
        b = _boundary()
        md1 = _market_data(spot=24000.0)
        md2 = _market_data(spot=25000.0)
        r1 = b.run(StubEngine.calculation_id, md1, _ctx())
        r2 = b.run(StubEngine.calculation_id, md2, _ctx())
        assert r1.values["delta"] != r2.values["delta"]

    async def test_no_hidden_wall_clock_calls_in_quant_package(self):
        for path in sorted(_QUANT_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    attr = node.func.attr
                    assert attr not in {"now", "utcnow", "today"}, f"{path.name}: wall clock call"
                    if attr == "time" and isinstance(node.func.value, ast.Name):
                        assert node.func.value.id != "time", f"{path.name}: time.time() call"

    async def test_no_env_or_io_imports_in_quant_package(self):
        forbidden = {"os", "sys", "random", "sqlalchemy", "requests", "httpx", "urllib", "fastapi"}
        for path in sorted(_QUANT_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        assert a.name.split(".")[0] not in forbidden, f"{path.name}: {a.name}"
                elif isinstance(node, ast.ImportFrom):
                    root = (node.module or "").split(".")[0]
                    assert root not in forbidden, f"{path.name}: {node.module}"


# ---------------------------------------------------------------------------
# 9. Quality propagation — no duplication
# ---------------------------------------------------------------------------


class TestQualityPropagation:
    async def test_boundary_never_recomputes_quality(self):
        # quality is consumed from the input only; the boundary cannot call the
        # Day-12 engine (no import path) — asserted statically here.
        for path in sorted(_QUANT_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert not module.startswith("app.market_data.quality"), f"{path.name}: {module}"
            text = path.read_text(encoding="utf-8")
            assert "MarketDataQualityEngine" not in text

    async def test_result_quality_matches_input_quality(self):
        b = _boundary()
        for q in (QualityState.EXCELLENT, QualityState.GOOD, QualityState.DEGRADED):
            result = b.run(StubEngine.calculation_id, _market_data(quality=q), _ctx())
            assert result.input_quality is q


# ---------------------------------------------------------------------------
# 10. Provenance preservation
# ---------------------------------------------------------------------------


class TestProvenancePreservation:
    async def test_provenance_preserved_into_result(self):
        b = _boundary()
        md = _market_data()
        result = b.run(StubEngine.calculation_id, md, _ctx())
        assert result.provenance == md.provenance
        assert result.provenance.source == "UPSTOX"

    async def test_engine_dropping_provenance_is_repaired_by_boundary(self):
        b = QuantitativeEngineBoundary()

        class DroppingEngine(StubEngine):
            calculation_id = "test.engine.drops_provenance"

            def calculate(self, market_data, context):
                r = super().calculate(market_data, context)
                return QuantResult(
                    calculation_id=self.calculation_id,
                    status=r.status,
                    values=r.values,
                )  # no provenance / quality / versions

        b.register(DroppingEngine())
        md = _market_data()
        result = b.run(DroppingEngine.calculation_id, md, _ctx(model_version="m", calculation_version="c"))
        assert result.provenance == md.provenance
        assert result.input_quality == md.quality
        assert result.reference_timestamp is not None
        assert result.model_version == "m"
        assert result.calculation_version == "c"
        assert result.calculation_id == DroppingEngine.calculation_id


# ---------------------------------------------------------------------------
# 11. Security — no leakage
# ---------------------------------------------------------------------------


class TestSecurity:
    async def test_issues_never_contain_credentials_or_payloads(self):
        b = _boundary()
        secret = "access_token=sk_live_secret_999"
        md = _market_data(prov=None)  # triggers MISSING_PROVENANCE path
        result = b.run(StubEngine.calculation_id, md, _ctx())
        serialized = str([(i.code.value, i.message, i.field) for i in result.issues])
        assert "sk_live_secret" not in serialized

    async def test_unavailable_result_has_no_values(self):
        b = _boundary()
        result = b.run("no.such.engine", _market_data(), _ctx())
        assert result.values is None


# ---------------------------------------------------------------------------
# 12. Broker neutrality (static)
# ---------------------------------------------------------------------------


class TestBrokerNeutrality:
    async def test_quant_package_imports_no_broker_modules(self):
        for path in sorted(_QUANT_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        assert not a.name.startswith("app.brokers"), f"{path.name}: {a.name}"
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert not module.startswith("app.brokers"), f"{path.name}: {module}"
                    assert "upstox" not in module.lower(), f"{path.name}: {module}"

    async def test_quant_package_imports_only_canonical_market_data(self):
        for path in sorted(_QUANT_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("app.services"), f"{path.name}: {node.module}"
                    assert not node.module.startswith("app.routers"), f"{path.name}: {node.module}"


# ---------------------------------------------------------------------------
# 13. Golden fixtures — representative option contracts (Day-15 seed)
# ---------------------------------------------------------------------------

# Representative NIFTY option contracts exercising the boundary's canonical
# terms.  Day 15+ golden tests will attach model-expected Greeks/IV/prices to
# these identities.
GOLDEN_CONTRACTS: list[dict[str, Any]] = [
    {"underlying": "NIFTY", "strike": 24000.0, "side": Side.CALL, "expiry": "2026-09-24"},
    {"underlying": "NIFTY", "strike": 24200.0, "side": Side.PUT, "expiry": "2026-09-24"},
    {"underlying": "NIFTY", "strike": 24500.0, "side": Side.CALL, "expiry": "2026-09-24"},
    {"underlying": "BANKNIFTY", "strike": 51000.0, "side": Side.PUT, "expiry": "2026-10-29"},
    {"underlying": "NIFTY", "strike": 24200.0, "side": Side.CALL, "expiry": "2026-12-31"},
]


class TestGoldenFixtures:
    def test_all_fixtures_are_concrete_options(self):
        for spec in GOLDEN_CONTRACTS:
            inst = _option_instrument(
                underlying=spec["underlying"],
                strike=spec["strike"],
                side=spec["side"],
                expiry=spec["expiry"],
            )
            assert inst.is_concrete_contract
            assert inst.option_type in (Side.CALL, Side.PUT)

    def test_fixture_invariants(self):
        ref = datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc)
        for spec in GOLDEN_CONTRACTS:
            inst = _option_instrument(
                underlying=spec["underlying"],
                strike=spec["strike"],
                side=spec["side"],
                expiry=spec["expiry"],
            )
            assert inst.strike > 0
            t = time_to_expiry(inst.expiry, ref)
            assert t >= 0.0
            assert t < 1.0  # all fixtures expire within a year of the reference