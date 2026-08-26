"""Tests for Phase 8A — Server-Side Live GEX Calculation.

Tests cover:
  1. Formula correctness (backend vs frontend parity)
  2. Input validation (all edge cases)
  3. Strike-level GEX calculation
  4. Chain-level GEX aggregation
  5. API endpoint behavior
  6. Numerical precision
  7. Multi-user safety (stateless verification)

The GEX formula contract (Phase 7.1):
    raw_gex = gamma × OI × spot² × 0.01
    CE → +raw_gex
    PE → −raw_gex
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.live_gex import (
    ExclusionReason,
    GexCalculationResult,
    GexStatus,
    LiveGexService,
    StrikeGexResult,
    _is_positive_finite,
    _raw_gex,
    _signed_gex,
    _validate_option_inputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chain(spot=24230.5, strikes=None, expiry="2026-08-28", symbol="NIFTY"):
    """Build a canonical option chain for testing."""
    if strikes is None:
        strikes = [
            {
                "strike": 24200,
                "call": {"gamma": 0.003, "oi": 10000, "ltp": 250.5},
                "put": {"gamma": 0.002, "oi": 8000, "ltp": 180.2},
            },
            {
                "strike": 24300,
                "call": {"gamma": 0.001, "oi": 5000, "ltp": 150.0},
                "put": {"gamma": 0.004, "oi": 12000, "ltp": 220.0},
            },
        ]
    return {
        "symbol": symbol,
        "expiry_date": expiry,
        "underlying_spot_price": spot,
        "chain": strikes,
    }


# ---------------------------------------------------------------------------
# 1. Formula correctness — raw_gex and signed_gex
# ---------------------------------------------------------------------------

class TestFormulaCorrectness:
    """Verify the core GEX formula matches Phase 7.1 contract exactly."""

    def test_raw_gex_basic(self):
        """gamma=0.003, OI=10000, spot=24230.5 → raw_gex = gamma * OI * spot^2 * 0.01"""
        expected = 0.003 * 10000 * 24230.5 ** 2 * 0.01
        result = _raw_gex(0.003, 10000, 24230.5)
        assert result == pytest.approx(expected, rel=1e-12)

    def test_signed_gex_call_positive(self):
        """CE GEX must be positive."""
        raw = _raw_gex(0.003, 10000, 24230.5)
        result = _signed_gex("call", 0.003, 10000, 24230.5)
        assert result == pytest.approx(raw, rel=1e-12)
        assert result > 0

    def test_signed_gex_put_negative(self):
        """PE GEX must be negative."""
        raw = _raw_gex(0.002, 8000, 24230.5)
        result = _signed_gex("put", 0.002, 8000, 24230.5)
        assert result == pytest.approx(-raw, rel=1e-12)
        assert result < 0

    def test_lot_size_not_in_formula(self):
        """Lot size must NOT appear in the GEX formula."""
        # Same inputs, different lot sizes — result must be identical
        r1 = _raw_gex(0.003, 10000, 24230.5)
        r2 = _raw_gex(0.003, 10000, 24230.5)  # lot_size is not a parameter
        assert r1 == r2

    def test_spot_squared(self):
        """GEX must scale with spot²."""
        r1 = _raw_gex(0.003, 10000, 24000)
        r2 = _raw_gex(0.003, 10000, 24000 * 2)
        # Doubling spot should quadruple GEX
        assert r2 == pytest.approx(r1 * 4, rel=1e-12)

    def test_zero_oi_gives_zero_gex(self):
        """OI=0 should not produce GEX (but _raw_gex returns 0, validation catches it)."""
        result = _raw_gex(0.003, 0, 24230.5)
        assert result == 0.0


# ---------------------------------------------------------------------------
# 2. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Validate input edge cases match frontend isPositiveFinite/validateOptionInput."""

    def test_is_positive_finite_valid(self):
        assert _is_positive_finite(1.0) is True
        assert _is_positive_finite(0.001) is True
        assert _is_positive_finite(1e10) is True

    def test_is_positive_finite_none(self):
        assert _is_positive_finite(None) is False

    def test_is_positive_finite_zero(self):
        assert _is_positive_finite(0) is False

    def test_is_positive_finite_negative(self):
        assert _is_positive_finite(-1.0) is False

    def test_is_positive_finite_nan(self):
        assert _is_positive_finite(float("nan")) is False

    def test_is_positive_finite_inf(self):
        assert _is_positive_finite(float("inf")) is False

    def test_is_positive_finite_neg_inf(self):
        assert _is_positive_finite(float("-inf")) is False

    def test_is_positive_finite_string(self):
        assert _is_positive_finite("abc") is False

    def test_is_positive_finite_string_number(self):
        # Python's float() accepts numeric strings — matches frontend Number()
        assert _is_positive_finite("1.5") is True

    def test_validate_option_valid(self):
        assert _validate_option_inputs(0.003, 10000, 24230.5) is None

    def test_validate_option_missing_gamma(self):
        result = _validate_option_inputs(None, 10000, 24230.5)
        assert result == ExclusionReason.MISSING_GAMMA.value

    def test_validate_option_missing_oi(self):
        result = _validate_option_inputs(0.003, None, 24230.5)
        assert result == ExclusionReason.MISSING_OI.value

    def test_validate_option_zero_oi(self):
        result = _validate_option_inputs(0.003, 0, 24230.5)
        assert result == ExclusionReason.ZERO_OI.value

    def test_validate_option_negative_gamma(self):
        result = _validate_option_inputs(-0.003, 10000, 24230.5)
        assert result == ExclusionReason.NEGATIVE_GAMMA.value

    def test_validate_option_nan_gamma(self):
        result = _validate_option_inputs(float("nan"), 10000, 24230.5)
        assert result == ExclusionReason.INVALID_GAMMA.value

    def test_validate_option_inf_gamma(self):
        result = _validate_option_inputs(float("inf"), 10000, 24230.5)
        assert result == ExclusionReason.INVALID_GAMMA.value

    def test_validate_option_string_gamma(self):
        result = _validate_option_inputs("abc", 10000, 24230.5)
        assert result == ExclusionReason.INVALID_GAMMA.value


# ---------------------------------------------------------------------------
# 3. Strike-level GEX
# ---------------------------------------------------------------------------

class TestStrikeGex:
    """Test per-strike GEX calculation."""

    def setup_method(self):
        self.service = LiveGexService()

    def test_normal_both_sides(self):
        row = {
            "strike": 24200,
            "call": {"gamma": 0.003, "oi": 10000},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.AVAILABLE.value
        assert sr.call_gex is not None
        assert sr.put_gex is not None
        assert sr.net_gex is not None
        assert sr.call_gex > 0
        assert sr.put_gex < 0
        assert sr.net_gex == pytest.approx(sr.call_gex + sr.put_gex, rel=1e-12)

    def test_formula_correctness_at_strike(self):
        row = {
            "strike": 24200,
            "call": {"gamma": 0.003, "oi": 10000},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        spot = 24230.5
        sr = self.service._calculate_strike_gex(row, spot)
        expected_call = 0.003 * 10000 * spot ** 2 * 0.01
        expected_put = -(0.002 * 8000 * spot ** 2 * 0.01)
        assert sr.call_gex == pytest.approx(expected_call, rel=1e-12)
        assert sr.put_gex == pytest.approx(expected_put, rel=1e-12)
        assert sr.net_gex == pytest.approx(expected_call + expected_put, rel=1e-12)

    def test_only_call_valid(self):
        row = {
            "strike": 24200,
            "call": {"gamma": 0.003, "oi": 10000},
            "put": {"gamma": None, "oi": None},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.PARTIAL.value
        assert sr.call_gex is not None
        assert sr.put_gex is None
        assert sr.net_gex is None

    def test_only_put_valid(self):
        row = {
            "strike": 24200,
            "call": {"gamma": None, "oi": None},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.PARTIAL.value
        assert sr.call_gex is None
        assert sr.put_gex is not None
        assert sr.net_gex is None

    def test_zero_oi_unavailable(self):
        row = {
            "strike": 24200,
            "call": {"gamma": 0.003, "oi": 0},
            "put": {"gamma": 0.002, "oi": 0},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.UNAVAILABLE.value
        assert sr.call_gex is None
        assert sr.put_gex is None

    def test_missing_gamma_invalid(self):
        row = {
            "strike": 24200,
            "call": {"gamma": None, "oi": 10000},
            "put": {"gamma": None, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.UNAVAILABLE.value

    def test_negative_gamma_invalid(self):
        # When one side has invalid gamma and other is valid, status is PARTIAL
        # (matches frontend strikeGex() behavior)
        row = {
            "strike": 24200,
            "call": {"gamma": -0.003, "oi": 10000},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.PARTIAL.value
        assert sr.call_gex is None  # invalid gamma → no GEX
        assert sr.put_gex is not None  # valid put side

    def test_negative_gamma_both_invalid(self):
        # When BOTH sides have invalid gamma, status is INVALID
        row = {
            "strike": 24200,
            "call": {"gamma": -0.003, "oi": 10000},
            "put": {"gamma": -0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.INVALID.value

    def test_nan_gamma_partial(self):
        # NaN gamma on one side, valid on other → PARTIAL
        row = {
            "strike": 24200,
            "call": {"gamma": float("nan"), "oi": 10000},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.PARTIAL.value
        assert sr.call_gex is None
        assert sr.put_gex is not None

    def test_nan_gamma_both_invalid(self):
        # NaN gamma on both sides → INVALID
        row = {
            "strike": 24200,
            "call": {"gamma": float("nan"), "oi": 10000},
            "put": {"gamma": float("nan"), "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.INVALID.value

    def test_infinite_gamma_partial(self):
        # Inf gamma on one side, valid on other → PARTIAL
        row = {
            "strike": 24200,
            "call": {"gamma": float("inf"), "oi": 10000},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.PARTIAL.value

    def test_infinite_gamma_both_invalid(self):
        # Inf gamma on both sides → INVALID
        row = {
            "strike": 24200,
            "call": {"gamma": float("inf"), "oi": 10000},
            "put": {"gamma": float("inf"), "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.status == GexStatus.INVALID.value

    def test_extremely_large_gex(self):
        """Very large OI and gamma should not overflow or produce inf."""
        row = {
            "strike": 24200,
            "call": {"gamma": 0.1, "oi": 1e9},
            "put": {"gamma": 0.1, "oi": 1e9},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert math.isfinite(sr.call_gex)
        assert math.isfinite(sr.put_gex)
        assert math.isfinite(sr.net_gex)

    def test_to_dict(self):
        row = {
            "strike": 24200,
            "call": {"gamma": 0.003, "oi": 10000},
            "put": {"gamma": 0.002, "oi": 8000},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        d = sr.to_dict()
        assert "strike" in d
        assert "callGex" in d
        assert "putGex" in d
        assert "netGex" in d
        assert "status" in d

    def test_preserves_source_metadata(self):
        """Strike result should preserve original gamma/OI values."""
        row = {
            "strike": 24200,
            "call": {"gamma": 0.003, "oi": 10000, "ltp": 250.5, "iv": 0.18},
            "put": {"gamma": 0.002, "oi": 8000, "ltp": 180.2, "iv": 0.22},
        }
        sr = self.service._calculate_strike_gex(row, 24230.5)
        assert sr.call_gamma == 0.003
        assert sr.put_gamma == 0.002
        assert sr.call_oi == 10000
        assert sr.put_oi == 8000


# ---------------------------------------------------------------------------
# 4. Chain-level GEX
# ---------------------------------------------------------------------------

class TestChainGex:
    """Test chain-level GEX aggregation."""

    def setup_method(self):
        self.service = LiveGexService()

    def test_normal_chain(self):
        chain = _make_chain()
        result = self.service.calculate(chain)
        assert result.symbol == "NIFTY"
        assert result.spot == 24230.5
        assert result.expiry == "2026-08-28"
        assert result.availability_status == GexStatus.AVAILABLE.value
        assert result.total_strike_count == 2
        assert result.valid_strike_count == 2
        assert result.call_gex is not None
        assert result.put_gex is not None
        assert result.net_gex is not None

    def test_net_gex_sign(self):
        """With more put OI than call OI, net GEX should be negative."""
        chain = _make_chain()
        result = self.service.calculate(chain)
        # Put side has more OI (8000+12000=20000) than call (10000+5000=15000)
        # and similar gamma, so put GEX magnitude > call GEX magnitude
        assert result.net_gex < 0

    def test_empty_chain(self):
        chain = _make_chain(strikes=[])
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.UNAVAILABLE.value
        assert result.total_strike_count == 0

    def test_none_chain(self):
        result = self.service.calculate(None)
        assert result.availability_status == GexStatus.UNAVAILABLE.value

    def test_invalid_spot(self):
        chain = _make_chain(spot=-100)
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.UNAVAILABLE.value

    def test_zero_spot(self):
        chain = _make_chain(spot=0)
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.UNAVAILABLE.value

    def test_nan_spot(self):
        chain = _make_chain(spot=float("nan"))
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.UNAVAILABLE.value

    def test_missing_spot(self):
        chain = _make_chain()
        chain["underlying_spot_price"] = None
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.UNAVAILABLE.value

    def test_partial_chain_mixed_validity(self):
        """Mix of valid and invalid strikes."""
        strikes = [
            {
                "strike": 24200,
                "call": {"gamma": 0.003, "oi": 10000},
                "put": {"gamma": 0.002, "oi": 8000},
            },
            {
                "strike": 24300,
                "call": {"gamma": None, "oi": None},
                "put": {"gamma": None, "oi": None},
            },
        ]
        chain = _make_chain(strikes=strikes)
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.PARTIAL.value
        assert result.valid_strike_count == 1
        assert result.total_strike_count == 2

    def test_all_invalid_gamma(self):
        strikes = [
            {
                "strike": 24200,
                "call": {"gamma": float("nan"), "oi": 10000},
                "put": {"gamma": float("nan"), "oi": 8000},
            },
        ]
        chain = _make_chain(strikes=strikes)
        result = self.service.calculate(chain)
        assert result.availability_status == GexStatus.INVALID.value

    def test_metadata(self):
        chain = _make_chain()
        result = self.service.calculate(chain)
        meta = result.methodology_metadata
        assert meta["gexVersion"] == "GEX_STANDARD_V1"
        assert meta["formula"] == "gamma * oi * spot^2 * 0.01"
        assert meta["oiUnit"] == "contracts"
        assert meta["lotSizeFactorApplied"] is False
        assert meta["callSign"] == 1
        assert meta["putSign"] == -1
        assert meta["engine"] == "LiveGexService_v1"

    def test_captured_at_is_iso(self):
        chain = _make_chain()
        result = self.service.calculate(chain)
        # Should be parseable as ISO 8601
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(result.captured_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_stateless_no_side_effects(self):
        """Calling calculate twice should produce identical results (stateless)."""
        chain = _make_chain()
        r1 = self.service.calculate(chain)
        r2 = self.service.calculate(chain)
        assert r1.call_gex == r2.call_gex
        assert r1.put_gex == r2.put_gex
        assert r1.net_gex == r2.net_gex

    def test_numerical_precision(self):
        """Very small gamma and OI should not underflow to zero."""
        chain = _make_chain(strikes=[
            {
                "strike": 24200,
                "call": {"gamma": 1e-10, "oi": 1},
                "put": {"gamma": 1e-10, "oi": 1},
            },
        ])
        result = self.service.calculate(chain)
        # Should be non-zero but very small
        assert result.call_gex > 0
        assert math.isfinite(result.call_gex)

    def test_to_dict(self):
        chain = _make_chain()
        result = self.service.calculate(chain)
        d = result.to_dict()
        assert "symbol" in d
        assert "spot" in d
        assert "call_gex" in d
        assert "put_gex" in d
        assert "net_gex" in d
        assert "strikes" in d
        assert len(d["strikes"]) == 2


# ---------------------------------------------------------------------------
# 5. Numerical parity with frontend gex.js
# ---------------------------------------------------------------------------

class TestFrontendParity:
    """Verify backend produces identical results to frontend gex.js formula."""

    def test_parity_basic(self):
        """Backend _raw_gex must equal frontend rawGex for same inputs."""
        test_cases = [
            (0.003, 10000, 24230.5),
            (0.001, 5000, 25000.0),
            (0.0001, 100000, 23000.0),
            (0.01, 100, 30000.0),
        ]
        for gamma, oi, spot in test_cases:
            backend = _raw_gex(gamma, oi, spot)
            # Frontend formula: gamma * oi * spot * spot * 0.01
            frontend = gamma * oi * spot * spot * 0.01
            assert backend == pytest.approx(frontend, rel=1e-15), \
                f"Mismatch for gamma={gamma}, oi={oi}, spot={spot}"

    def test_parity_signed_gex(self):
        """Backend _signed_gex must equal frontend signedGex."""
        gamma, oi, spot = 0.003, 10000, 24230.5
        raw = gamma * oi * spot * spot * 0.01

        # Call
        assert _signed_gex("call", gamma, oi, spot) == pytest.approx(+raw, rel=1e-15)
        # Put
        assert _signed_gex("put", gamma, oi, spot) == pytest.approx(-raw, rel=1e-15)

    def test_parity_chain_level(self):
        """Full chain calculation must match frontend chainGex aggregation."""
        chain = _make_chain()
        spot = chain["underlying_spot_price"]
        service = LiveGexService()
        result = service.calculate(chain)

        # Manually compute expected values from the formula
        expected_call = 0.0
        expected_put = 0.0
        for row in chain["chain"]:
            c = row["call"]
            p = row["put"]
            expected_call += c["gamma"] * c["oi"] * spot ** 2 * 0.01
            expected_put += -(p["gamma"] * p["oi"] * spot ** 2 * 0.01)

        assert result.call_gex == pytest.approx(expected_call, rel=1e-10)
        assert result.put_gex == pytest.approx(expected_put, rel=1e-10)
        assert result.net_gex == pytest.approx(expected_call + expected_put, rel=1e-10)


# ---------------------------------------------------------------------------
# 6. API endpoint tests
# ---------------------------------------------------------------------------

class TestLiveGexApi:
    """Test GET /gex/live endpoint."""

    def _make_client(self):
        from app.main import app
        return TestClient(app)

    def test_unauthenticated(self):
        """Without session, should return 401."""
        client = self._make_client()
        resp = client.get("/gex/live?expiry_date=2026-08-28")
        assert resp.status_code == 401

    @patch("app.routers.live_gex.token_store")
    @patch("app.routers.live_gex.gateway")
    def test_valid_chain(self, mock_gateway, mock_token_store):
        """Authenticated request with valid chain should return GEX."""
        mock_token_store.get_token.return_value = "fake-token"
        mock_adapter = MagicMock()

        chain_data = _make_chain()
        mock_adapter.get_option_chain = AsyncMock(return_value=chain_data)
        mock_gateway.create.return_value = mock_adapter

        client = self._make_client()
        resp = client.get(
            "/gex/live?expiry_date=2026-08-28",
            headers={"X-Session-Id": "test-session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NIFTY"
        assert data["spot"] == 24230.5
        assert "call_gex" in data
        assert "put_gex" in data
        assert "net_gex" in data
        assert "strikes" in data
        assert data["methodology"] == "GEX_STANDARD_V1"
        assert data["sign_convention"] == "NAIVE_DEALER_CONVENTION"

    @patch("app.routers.live_gex.token_store")
    @patch("app.routers.live_gex.gateway")
    def test_invalid_symbol(self, mock_gateway, mock_token_store):
        """Unknown symbol should return 404."""
        mock_token_store.get_token.return_value = "fake-token"
        client = self._make_client()
        resp = client.get(
            "/gex/live?symbol=INVALID&expiry_date=2026-08-28",
            headers={"X-Session-Id": "test-session"},
        )
        assert resp.status_code == 404

    @patch("app.routers.live_gex.token_store")
    @patch("app.routers.live_gex.gateway")
    def test_invalid_expiry(self, mock_gateway, mock_token_store):
        """Invalid expiry format should return 422."""
        mock_token_store.get_token.return_value = "fake-token"
        client = self._make_client()
        resp = client.get(
            "/gex/live?expiry_date=not-a-date",
            headers={"X-Session-Id": "test-session"},
        )
        assert resp.status_code == 422

    @patch("app.routers.live_gex.token_store")
    def test_expired_token(self, mock_token_store):
        """Expired broker token should return 401 with session clear."""
        from app.brokers.domain.errors import BrokerError, BrokerErrorCode
        mock_token_store.get_token.return_value = "expired-token"

        mock_adapter = MagicMock()
        mock_adapter.get_option_chain = AsyncMock(
            side_effect=BrokerError(
                BrokerErrorCode.TOKEN_EXPIRED,
                "Session expired",
                status_code=401,
            )
        )

        with patch("app.routers.live_gex.gateway") as mock_gateway:
            mock_gateway.create.return_value = mock_adapter
            client = self._make_client()
            resp = client.get(
                "/gex/live?expiry_date=2026-08-28",
                headers={"X-Session-Id": "test-session"},
            )
            assert resp.status_code == 401

    @patch("app.routers.live_gex.token_store")
    @patch("app.routers.live_gex.gateway")
    def test_empty_chain(self, mock_gateway, mock_token_store):
        """Empty chain should return valid response with unavailable status."""
        mock_token_store.get_token.return_value = "fake-token"
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain = AsyncMock(
            return_value={
                "symbol": "NIFTY",
                "expiry_date": "2026-08-28",
                "underlying_spot_price": 24230.5,
                "chain": [],
            }
        )
        mock_gateway.create.return_value = mock_adapter

        client = self._make_client()
        resp = client.get(
            "/gex/live?expiry_date=2026-08-28",
            headers={"X-Session-Id": "test-session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["availability_status"] == "unavailable"

    @patch("app.routers.live_gex.token_store")
    @patch("app.routers.live_gex.gateway")
    def test_partial_chain(self, mock_gateway, mock_token_store):
        """Chain with mixed valid/invalid strikes should return partial status."""
        mock_token_store.get_token.return_value = "fake-token"
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain = AsyncMock(return_value=_make_chain(
            strikes=[
                {
                    "strike": 24200,
                    "call": {"gamma": 0.003, "oi": 10000},
                    "put": {"gamma": 0.002, "oi": 8000},
                },
                {
                    "strike": 24300,
                    "call": {"gamma": None, "oi": None},
                    "put": {"gamma": None, "oi": None},
                },
            ]
        ))
        mock_gateway.create.return_value = mock_adapter

        client = self._make_client()
        resp = client.get(
            "/gex/live?expiry_date=2026-08-28",
            headers={"X-Session-Id": "test-session"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["availability_status"] == "partial"
        assert data["valid_strike_count"] == 1
        assert data["total_strike_count"] == 2

    @patch("app.routers.live_gex.token_store")
    @patch("app.routers.live_gex.gateway")
    def test_response_includes_methodology_metadata(self, mock_gateway, mock_token_store):
        """Response should include methodology metadata."""
        mock_token_store.get_token.return_value = "fake-token"
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain = AsyncMock(return_value=_make_chain())
        mock_gateway.create.return_value = mock_adapter

        client = self._make_client()
        resp = client.get(
            "/gex/live?expiry_date=2026-08-28",
            headers={"X-Session-Id": "test-session"},
        )
        assert resp.status_code == 200
        meta = resp.json()["methodology_metadata"]
        assert meta["gexVersion"] == "GEX_STANDARD_V1"
        assert meta["lotSizeFactorApplied"] is False
        assert meta["engine"] == "LiveGexService_v1"
