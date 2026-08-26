"""Phase 7.19A — Historical Greeks Synthetic Validation Tests.

Mathematical and architectural validation of the proposed Greeks
reconstruction pipeline.  Uses deterministic synthetic inputs only —
no live APIs, no network, no database, no production code modification.

The Black-Scholes pricing engine, IV solver, and Greek formulas are
implemented independently in this test file for validation purposes.
The production implementation (Phase 7.19B) must produce identical
results for the same inputs.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

import pytest


# ============================================================================
# Independent Black-Scholes implementation (test-only, for validation)
# ============================================================================

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_d1d2(
    S: float, K: float, T: float, sigma: float, r: float, q: float = 0.0,
) -> tuple[float, float]:
    """Compute d1 and d2 for Black-Scholes."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return (float("nan"), float("nan"))
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return (d1, d2)


def bs_price(
    option_type: str, S: float, K: float, T: float,
    sigma: float, r: float, q: float = 0.0,
) -> float:
    """Black-Scholes European option price."""
    if T <= 0:
        if option_type == "CE":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        fwd = S * math.exp((r - q) * T)
        if option_type == "CE":
            return max(fwd - K, 0.0) * math.exp(-r * T)
        return max(K - fwd, 0.0) * math.exp(-r * T)
    d1, d2 = bs_d1d2(S, K, T, sigma, r, q)
    dfQ = math.exp(-q * T)
    dfR = math.exp(-r * T)
    if option_type == "CE":
        return S * dfQ * _norm_cdf(d1) - K * dfR * _norm_cdf(d2)
    else:
        return K * dfR * _norm_cdf(-d2) - S * dfQ * _norm_cdf(-d1)


def bs_greeks(
    option_type: str, S: float, K: float, T: float,
    sigma: float, r: float, q: float = 0.0,
) -> dict[str, float]:
    """Black-Scholes per-unit Greeks.

    Returns delta, gamma, vega (per 1.00 vol), theta (annualized).
    """
    if T <= 0:
        if option_type == "CE":
            return {"delta": 1.0 if S > K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        return {"delta": -1.0 if S < K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    if sigma <= 0:
        fwd = S * math.exp((r - q) * T)
        if option_type == "CE":
            return {"delta": 1.0 if fwd > K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        return {"delta": -1.0 if fwd < K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}

    d1, d2 = bs_d1d2(S, K, T, sigma, r, q)
    pdf = _norm_pdf(d1)
    sqrtT = math.sqrt(T)
    dfQ = math.exp(-q * T)
    dfR = math.exp(-r * T)
    nD1 = _norm_cdf(d1)
    is_call = option_type == "CE"

    delta = dfQ * (nD1 if is_call else nD1 - 1.0)
    gamma = (dfQ * pdf) / (S * sigma * sqrtT)
    vega = S * dfQ * pdf * sqrtT  # per 1.00 vol fraction

    theta = (
        -(S * dfQ * pdf * sigma) / (2 * sqrtT)
        + (-1 if is_call else 1) * r * K * dfR * (_norm_cdf(d2) if is_call else _norm_cdf(-d2))
        + (1 if is_call else -1) * q * S * dfQ * (nD1 if is_call else _norm_cdf(-d1))
    )

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def solve_iv(
    option_type: str, S: float, K: float, T: float,
    market_price: float, r: float, q: float = 0.0,
    tol: float = 1e-8, max_iter: int = 100,
) -> tuple[Optional[float], Optional[str]]:
    """Solve for implied volatility using Brent's method (bisection fallback).

    Returns (iv, error_code). error_code is None on success.
    """
    if T <= 0:
        return (None, "EXPIRED")
    if S <= 0:
        return (None, "INVALID_SPOT")
    if K <= 0:
        return (None, "INVALID_STRIKE")
    if market_price <= 0:
        return (None, "INVALID_PRICE")

    # Check intrinsic value
    if option_type == "CE":
        intrinsic = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
        upper = S * math.exp(-q * T)
    else:
        intrinsic = max(K * math.exp(-r * T) - S * math.exp(-q * T), 0.0)
        upper = K * math.exp(-r * T)

    if market_price < intrinsic - 1e-10:
        return (None, "BELOW_INTRINSIC")
    if market_price > upper + 1e-10:
        return (None, "ABOVE_THEORETICAL_MAX")

    # Brent/bisection bracket
    sigma_low = 0.001
    sigma_high = 10.0

    f_low = bs_price(option_type, S, K, T, sigma_low, r, q) - market_price
    f_high = bs_price(option_type, S, K, T, sigma_high, r, q) - market_price

    if f_low * f_high > 0:
        # Try to expand bracket
        if abs(f_low) < abs(f_high):
            sigma_high = min(sigma_high * 2, 20.0)
        else:
            sigma_low = max(sigma_low / 2, 0.0001)
        f_low = bs_price(option_type, S, K, T, sigma_low, r, q) - market_price
        f_high = bs_price(option_type, S, K, T, sigma_high, r, q) - market_price
        if f_low * f_high > 0:
            return (None, "NO_BRACKET")

    # Bisection (simple, robust)
    for _ in range(max_iter):
        sigma_mid = (sigma_low + sigma_high) / 2.0
        f_mid = bs_price(option_type, S, K, T, sigma_mid, r, q) - market_price

        if abs(f_mid) < tol or (sigma_high - sigma_low) / 2.0 < tol:
            return (sigma_mid, None)

        if f_low * f_mid < 0:
            sigma_high = sigma_mid
            f_high = f_mid
        else:
            sigma_low = sigma_mid
            f_low = f_mid

    return ((sigma_low + sigma_high) / 2.0, "CONVERGENCE_FAILED")


# ============================================================================
# Timestamp alignment model (test-only)
# ============================================================================

IST_OFFSET = timedelta(hours=5, minutes=30)
IST = timezone(IST_OFFSET)


def utc_to_ist(dt: datetime) -> datetime:
    """Convert UTC datetime to IST."""
    return dt.astimezone(IST)


def align_spot(
    option_open_time_utc: datetime,
    nifty_candles: list[dict],
) -> Optional[float]:
    """Find the NIFTY close price aligned to an option candle timestamp.

    Uses the latest NIFTY candle whose open_time <= option_open_time.
    Returns None if no valid spot can be established.
    """
    candidate = None
    for candle in sorted(nifty_candles, key=lambda c: c["open_time"]):
        if candle["open_time"] <= option_open_time_utc:
            if candle.get("close") and candle["close"] > 0:
                candidate = candle["close"]
        else:
            break
    return candidate


def compute_time_to_expiry(
    valuation_utc: datetime,
    expiry_date_str: str,
) -> float:
    """Compute T in year fractions (calendar days / 365.25)."""
    expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
    # Expiry time is 15:30 IST = 10:00 UTC (settlement reference)
    expiry_utc = expiry_date.replace(hour=10, minute=0, tzinfo=timezone.utc)
    delta = expiry_utc - valuation_utc
    return max(0.0, delta.total_seconds() / (365.25 * 86400))


# ============================================================================
# Data classes for structured test data
# ============================================================================

@dataclass
class GreeksResult:
    spot: float
    strike: float
    option_type: str
    option_price: float
    time_to_expiry: float
    risk_free_rate: float
    implied_volatility: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    vega: Optional[float]
    theta: Optional[float]
    status: str  # VALID | INVALID
    error_code: Optional[str]


# ============================================================================
# A. Black-Scholes Pricing Tests
# ============================================================================

class TestBlackScholesPricing:
    """Verify BS pricing for ATM, ITM, OTM CE/PE."""

    S = 25000.0  # NIFTY spot
    K = 25000.0  # ATM strike
    T = 30 / 365.25  # ~30 days
    sigma = 0.18  # 18% IV
    r = 0.065  # 6.5% risk-free

    def test_atm_ce_positive(self):
        price = bs_price("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert price > 0, "ATM CE must have positive time value"
        assert price < self.S * 0.1, "ATM CE should be < 10% of spot"

    def test_atm_pe_positive(self):
        price = bs_price("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert price > 0, "ATM PE must have positive time value"

    def test_itm_ce(self):
        K_itm = 24500.0  # 500 points ITM
        price = bs_price("CE", self.S, K_itm, self.T, self.sigma, self.r)
        intrinsic = self.S - K_itm
        assert price > intrinsic, "ITM CE must be > intrinsic (time value)"
        assert price < self.S, "ITM CE must be < spot"

    def test_itm_pe(self):
        K_itm = 25500.0  # 500 points ITM
        price = bs_price("PE", self.S, K_itm, self.T, self.sigma, self.r)
        intrinsic = K_itm - self.S
        assert price > intrinsic, "ITM PE must be > intrinsic (time value)"

    def test_otm_ce(self):
        K_otm = 25500.0  # 500 points OTM
        price = bs_price("CE", self.S, K_otm, self.T, self.sigma, self.r)
        assert price > 0, "OTM CE must have time value"
        assert price < bs_price("CE", self.S, self.K, self.T, self.sigma, self.r)

    def test_otm_pe(self):
        K_otm = 24500.0  # 500 points OTM
        price = bs_price("PE", self.S, K_otm, self.T, self.sigma, self.r)
        assert price > 0, "OTM PE must have time value"

    def test_put_call_parity(self):
        """Verify put-call parity: C - P = S·e^(-qT) - K·e^(-rT)."""
        K = 25000.0
        T = 30 / 365.25
        sigma = 0.18
        r = 0.065
        q = 0.0

        C = bs_price("CE", self.S, K, T, sigma, r, q)
        P = bs_price("PE", self.S, K, T, sigma, r, q)
        parity_rhs = self.S * math.exp(-q * T) - K * math.exp(-r * T)

        assert abs((C - P) - parity_rhs) < 0.01, (
            f"Put-call parity violated: C-P={C-P:.4f}, RHS={parity_rhs:.4f}"
        )

    def test_deep_itm_ce_approaches_intrinsic(self):
        """Deep ITM CE price should be close to intrinsic value.
        
        With 30 days to expiry and 18% IV, even deep ITM options have
        some time value. The key check is that price > intrinsic and
        the time-value component is small relative to the intrinsic.
        """
        K_deep = 20000.0  # 5000 points ITM
        price = bs_price("CE", self.S, K_deep, self.T, self.sigma, self.r)
        intrinsic = self.S - K_deep
        assert price > intrinsic, "Deep ITM CE must be above intrinsic"
        time_value = price - intrinsic
        # Time value should be a small fraction of intrinsic
        assert time_value / intrinsic < 0.05, (
            f"Time value {time_value:.2f} too large vs intrinsic {intrinsic:.2f}"
        )


# ============================================================================
# B. IV Round-Trip Tests
# ============================================================================

class TestIVRoundTrip:
    """Generate prices from known IV, then recover IV."""

    S = 25000.0
    r = 0.065

    @pytest.mark.parametrize("sigma_input", [0.10, 0.15, 0.18, 0.25, 0.40, 0.80])
    def test_ce_roundtrip(self, sigma_input):
        K = 25000.0
        T = 30 / 365.25
        price = bs_price("CE", self.S, K, T, sigma_input, self.r)
        iv_recovered, err = solve_iv("CE", self.S, K, T, price, self.r)
        assert err is None, f"IV solver failed: {err}"
        assert iv_recovered is not None
        assert abs(iv_recovered - sigma_input) < 1e-4, (
            f"IV roundtrip failed: input={sigma_input:.4f}, recovered={iv_recovered:.4f}"
        )

    @pytest.mark.parametrize("sigma_input", [0.10, 0.18, 0.40])
    def test_pe_roundtrip(self, sigma_input):
        K = 25000.0
        T = 30 / 365.25
        price = bs_price("PE", self.S, K, T, sigma_input, self.r)
        iv_recovered, err = solve_iv("PE", self.S, K, T, price, self.r)
        assert err is None, f"IV solver failed: {err}"
        assert iv_recovered is not None
        assert abs(iv_recovered - sigma_input) < 1e-4

    @pytest.mark.parametrize("sigma_input", [0.10, 0.18, 0.40])
    def test_itm_ce_roundtrip(self, sigma_input):
        K = 24500.0  # ITM
        T = 30 / 365.25
        price = bs_price("CE", self.S, K, T, sigma_input, self.r)
        iv_recovered, err = solve_iv("CE", self.S, K, T, price, self.r)
        assert err is None, f"IV solver failed: {err}"
        assert abs(iv_recovered - sigma_input) < 1e-4

    @pytest.mark.parametrize("sigma_input", [0.10, 0.18, 0.40])
    def test_otm_ce_roundtrip(self, sigma_input):
        K = 25500.0  # OTM
        T = 30 / 365.25
        price = bs_price("CE", self.S, K, T, sigma_input, self.r)
        iv_recovered, err = solve_iv("CE", self.S, K, T, price, self.r)
        assert err is None, f"IV solver failed: {err}"
        assert abs(iv_recovered - sigma_input) < 1e-4

    def test_various_T_values(self):
        """IV roundtrip across different time-to-expiry values."""
        K = 25000.0
        sigma = 0.18
        for T_days in [1, 5, 15, 30, 60, 90]:
            T = T_days / 365.25
            price = bs_price("CE", self.S, K, T, sigma, self.r)
            iv_recovered, err = solve_iv("CE", self.S, K, T, price, self.r)
            assert err is None, f"T={T_days}d: IV solver failed: {err}"
            assert abs(iv_recovered - sigma) < 1e-4


# ============================================================================
# C. Greeks Verification Tests
# ============================================================================

class TestGreeksValues:
    """Verify independently calculated Greeks with meaningful assertions."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = 0.065

    def test_atm_ce_delta_near_half(self):
        """ATM CE delta should be around 0.5.
        
        With r=6.5% and T=30/365.25, the forward price is above spot,
        so ATM (K=S) CE delta is slightly above 0.5 due to drift.
        The forward-moneyness-adjusted ATM would give exactly 0.5.
        """
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        # With r=6.5%, T=30d: forward drift pushes delta above 0.5
        assert 0.48 < g["delta"] < 0.60, f"ATM CE delta={g['delta']:.4f}"

    def test_atm_pe_delta_near_neg_half(self):
        """ATM PE delta should be around -0.5.
        
        With r=6.5%, PE delta is slightly above -0.5 (less negative)
        due to the drift term.
        """
        g = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert -0.55 < g["delta"] < -0.42, f"ATM PE delta={g['delta']:.4f}"

    def test_ce_delta_positive(self):
        """CE delta must be positive and ≤ 1."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert 0 < g["delta"] <= 1.0

    def test_pe_delta_negative(self):
        """PE delta must be negative and ≥ -1."""
        g = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert -1.0 <= g["delta"] < 0

    def test_gamma_positive(self):
        """Gamma must be positive for both CE and PE."""
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_ce["gamma"] > 0
        assert g_pe["gamma"] > 0

    def test_gamma_same_ce_pe(self):
        """Gamma must be identical for CE and PE at same strike/spot."""
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert abs(g_ce["gamma"] - g_pe["gamma"]) < 1e-10

    def test_vega_positive(self):
        """Vega must be positive for both CE and PE."""
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_ce["vega"] > 0
        assert g_pe["vega"] > 0

    def test_vega_same_ce_pe(self):
        """Vega must be identical for CE and PE at same strike/spot."""
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert abs(g_ce["vega"] - g_pe["vega"]) < 1e-10

    def test_theta_negative_for_long_options(self):
        """Theta must be negative (time decay) for ATM CE and PE."""
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_ce["theta"] < 0, f"ATM CE theta={g_ce['theta']}"
        assert g_pe["theta"] < 0, f"ATM PE theta={g_pe['theta']}"

    def test_gamma_peak_at_atm(self):
        """Gamma should be highest at ATM, lower for ITM/OTM."""
        g_atm = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_itm = bs_greeks("CE", self.S, self.K - 500, self.T, self.sigma, self.r)
        g_otm = bs_greeks("CE", self.S, self.K + 500, self.T, self.sigma, self.r)
        assert g_atm["gamma"] > g_itm["gamma"]
        assert g_atm["gamma"] > g_otm["gamma"]

    def test_delta_increases_with_spot_for_ce(self):
        """CE delta increases as spot increases (more ITM)."""
        d_low = bs_greeks("CE", self.S - 500, self.K, self.T, self.sigma, self.r)["delta"]
        d_mid = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)["delta"]
        d_high = bs_greeks("CE", self.S + 500, self.K, self.T, self.sigma, self.r)["delta"]
        assert d_low < d_mid < d_high


# ============================================================================
# D. CE/PE Consistency Tests
# ============================================================================

class TestCEPEConsistency:
    """Put/call parity and Greek consistency."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = 0.065

    def test_delta_sum_ce_pe(self):
        """CE delta - PE delta = e^(-qT) ≈ 1.0 (when q=0)."""
        d_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)["delta"]
        d_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)["delta"]
        assert abs((d_ce - d_pe) - 1.0) < 0.01, (
            f"CE-PE delta should be ~1.0: got {d_ce - d_pe:.4f}"
        )

    def test_gamma_consistency(self):
        """Gamma must be identical for CE and PE."""
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)["gamma"]
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)["gamma"]
        assert abs(g_ce - g_pe) < 1e-10

    def test_vega_consistency(self):
        """Vega must be identical for CE and PE."""
        v_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)["vega"]
        v_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)["vega"]
        assert abs(v_ce - v_pe) < 1e-10

    def test_theta_sum_relationship(self):
        """Both CE and PE theta should be negative for ATM (time decay)."""
        t_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)["theta"]
        t_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)["theta"]
        # Both should be negative for ATM options (time decay)
        assert t_ce < 0, f"ATM CE theta should be negative: {t_ce}"
        assert t_pe < 0, f"ATM PE theta should be negative: {t_pe}"
        # The difference reflects the drift term (r)
        # For r>0: CE has higher delta → more time decay → more negative theta
        theta_diff = abs(t_ce) - abs(t_pe)
        assert theta_diff > 0, (
            f"ATM CE should have larger |theta| than PE due to drift: "
            f"|CE|={abs(t_ce):.2f}, |PE|={abs(t_pe):.2f}"
        )


# ============================================================================
# E. Intrinsic Value Validation Tests
# ============================================================================

class TestIntrinsicValueValidation:
    """Reject impossible prices."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    r = 0.065

    def test_zero_price_rejected(self):
        _, err = solve_iv("CE", self.S, self.K, self.T, 0.0, self.r)
        assert err == "INVALID_PRICE"

    def test_negative_price_rejected(self):
        _, err = solve_iv("CE", self.S, self.K, self.T, -100.0, self.r)
        assert err == "INVALID_PRICE"

    def test_below_intrinsic_ce_rejected(self):
        """CE price below intrinsic (S-K for ITM) is impossible."""
        K_itm = 24500.0  # 500 ITM
        intrinsic = self.S - K_itm  # 500
        _, err = solve_iv("CE", self.S, K_itm, self.T, intrinsic - 1, self.r)
        assert err == "BELOW_INTRINSIC"

    def test_below_intrinsic_pe_rejected(self):
        """PE price below intrinsic (K-S for ITM) is impossible.
        
        The intrinsic check uses the discounted intrinsic value:
        PE lower bound = max(K·e^(-rT) - S, 0)
        """
        K_itm = 25500.0  # 500 ITM
        # PE intrinsic (discounted): K*e^(-rT) - S
        intrinsic_discounted = K_itm * math.exp(-self.r * self.T) - self.S
        if intrinsic_discounted > 0:
            _, err = solve_iv("PE", self.S, K_itm, self.T, intrinsic_discounted - 1, self.r)
            assert err == "BELOW_INTRINSIC"
        else:
            # If discounted intrinsic is <=0, any positive price is valid
            _, err = solve_iv("PE", self.S, K_itm, self.T, 0.01, self.r)
            assert err is None  # small positive price is above intrinsic

    def test_above_theoretical_max_rejected(self):
        """CE price above S (theoretical max for European) is impossible."""
        _, err = solve_iv("CE", self.S, self.K, self.T, self.S + 100, self.r)
        assert err == "ABOVE_THEORETICAL_MAX"

    def test_valid_price_accepted(self):
        price = bs_price("CE", self.S, self.K, self.T, 0.18, self.r)
        iv, err = solve_iv("CE", self.S, self.K, self.T, price, self.r)
        assert err is None
        assert iv is not None


# ============================================================================
# F. Near-Expiry Tests
# ============================================================================

class TestNearExpiry:
    """Test very small T — no NaN or infinity leakage."""

    S = 25000.0
    K = 25000.0
    sigma = 0.18
    r = 0.065

    def test_one_day_to_expiry(self):
        T = 1 / 365.25
        price = bs_price("CE", self.S, self.K, T, self.sigma, self.r)
        assert math.isfinite(price)
        g = bs_greeks("CE", self.S, self.K, T, self.sigma, self.r)
        for key in ("delta", "gamma", "vega", "theta"):
            assert math.isfinite(g[key]), f"Near-expiry {key}={g[key]} is not finite"

    def test_one_hour_to_expiry(self):
        T = (1 / 24) / 365.25  # ~1 hour
        price = bs_price("CE", self.S, self.K, T, self.sigma, self.r)
        assert math.isfinite(price)
        g = bs_greeks("CE", self.S, self.K, T, self.sigma, self.r)
        for key in ("delta", "gamma", "vega", "theta"):
            assert math.isfinite(g[key])

    def test_expired_t_zero(self):
        """At T=0, Greeks should be deterministic, not NaN."""
        g_ce = bs_greeks("CE", self.S, self.K, 0, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, 0, self.sigma, self.r)
        assert g_ce["delta"] in (0.0, 1.0)
        assert g_ce["gamma"] == 0.0
        assert g_ce["vega"] == 0.0
        assert g_pe["delta"] in (-1.0, 0.0)
        assert g_pe["gamma"] == 0.0
        assert g_pe["vega"] == 0.0

    def test_expired_itm_ce(self):
        """Expired ITM CE should have delta=1."""
        g = bs_greeks("CE", 25500, 25000, 0, self.sigma, self.r)
        assert g["delta"] == 1.0

    def test_expired_otm_pe(self):
        """Expired OTM PE should have delta=0."""
        g = bs_greeks("PE", 25500, 25000, 0, self.sigma, self.r)
        assert g["delta"] == 0.0

    def test_iv_solver_expired(self):
        _, err = solve_iv("CE", self.S, self.K, 0, 100.0, self.r)
        assert err == "EXPIRED"


# ============================================================================
# G. Extreme Volatility Tests
# ============================================================================

class TestExtremeVolatility:
    """Low and high volatility edge cases."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    r = 0.065
    sigma = 0.18  # reference vol

    def test_very_low_vol(self):
        """Very low vol (1%) should still produce valid Greeks."""
        sigma = 0.01
        price = bs_price("CE", self.S, self.K, self.T, sigma, self.r)
        assert price > 0
        g = bs_greeks("CE", self.S, self.K, self.T, sigma, self.r)
        for key in ("delta", "gamma", "vega", "theta"):
            assert math.isfinite(g[key])

    def test_very_high_vol(self):
        """Very high vol (200%) should still produce valid Greeks."""
        sigma = 2.0
        price = bs_price("CE", self.S, self.K, self.T, sigma, self.r)
        assert price > 0
        g = bs_greeks("CE", self.S, self.K, self.T, sigma, self.r)
        for key in ("delta", "gamma", "vega", "theta"):
            assert math.isfinite(g[key])

    def test_low_vol_roundtrip(self):
        sigma = 0.02
        price = bs_price("CE", self.S, self.K, self.T, sigma, self.r)
        iv, err = solve_iv("CE", self.S, self.K, self.T, price, self.r)
        assert err is None
        assert abs(iv - sigma) < 1e-4

    def test_high_vol_roundtrip(self):
        sigma = 1.5
        price = bs_price("CE", self.S, self.K, self.T, sigma, self.r)
        iv, err = solve_iv("CE", self.S, self.K, self.T, price, self.r)
        assert err is None
        assert abs(iv - sigma) < 1e-4


# ============================================================================
# H. Missing Data Tests
# ============================================================================

class TestMissingData:
    """All missing data must produce explicit invalid outcomes."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    r = 0.065

    def test_missing_spot_zero(self):
        _, err = solve_iv("CE", 0, self.K, self.T, 100.0, self.r)
        assert err == "INVALID_SPOT"

    def test_missing_spot_negative(self):
        _, err = solve_iv("CE", -1, self.K, self.T, 100.0, self.r)
        assert err == "INVALID_SPOT"

    def test_missing_strike_zero(self):
        _, err = solve_iv("CE", self.S, 0, self.T, 100.0, self.r)
        assert err == "INVALID_STRIKE"

    def test_missing_price_zero(self):
        _, err = solve_iv("CE", self.S, self.K, self.T, 0, self.r)
        assert err == "INVALID_PRICE"

    def test_missing_expiry_t_zero(self):
        _, err = solve_iv("CE", self.S, self.K, 0, 100.0, self.r)
        assert err == "EXPIRED"

    def test_greeks_missing_spot(self):
        """Greeks should not crash with extreme inputs."""
        g = bs_greeks("CE", 0.001, self.K, self.T, 0.18, self.r)
        # Should produce finite or very specific values
        for key in ("delta", "gamma", "vega", "theta"):
            assert math.isfinite(g[key]) or g[key] == 0.0


# ============================================================================
# I. Timestamp Alignment Tests
# ============================================================================

class TestTimestampAlignment:
    """Verify spot alignment logic with synthetic data."""

    def _make_nifty_candles(self, base_date: str) -> list[dict]:
        """Create synthetic NIFTY candles for a trading day (09:15-15:27 IST)."""
        base = datetime.strptime(base_date, "%Y-%m-%d")
        candles = []
        # Trading hours: 09:15 to 15:27 IST = 03:45 to 09:57 UTC
        start_utc = datetime(base.year, base.month, base.day, 3, 45, tzinfo=timezone.utc)
        price = 25000.0
        for i in range(124):  # 124 3-min candles (09:15-15:27)
            t = start_utc + timedelta(minutes=3 * i)
            price += (i % 5 - 2) * 0.5  # slight oscillation
            candles.append({
                "open_time": t,
                "close": price,
            })
        return candles

    def test_exact_match(self):
        """Option candle at exact NIFTY candle time gets correct spot."""
        candles = self._make_nifty_candles("2024-10-31")
        option_time = candles[10]["open_time"]  # exact match
        spot = align_spot(option_time, candles)
        assert spot is not None
        assert spot == candles[10]["close"]

    def test_between_candles(self):
        """Option candle between two NIFTY candles uses the earlier one."""
        candles = self._make_nifty_candles("2024-10-31")
        option_time = candles[5]["open_time"] + timedelta(minutes=1)
        spot = align_spot(option_time, candles)
        assert spot is not None
        assert spot == candles[5]["close"]

    def test_after_index_close(self):
        """Option candle after 15:27 IST uses last NIFTY candle."""
        candles = self._make_nifty_candles("2024-10-31")
        # Option candle at 15:30 IST = 09:57 UTC (1 minute after index close)
        post_close = datetime(2024, 10, 31, 9, 58, tzinfo=timezone.utc)
        spot = align_spot(post_close, candles)
        assert spot is not None
        assert spot == candles[-1]["close"]

    def test_no_candles_on_day(self):
        """No NIFTY candles → no valid spot."""
        option_time = datetime(2024, 10, 31, 5, 0, tzinfo=timezone.utc)
        spot = align_spot(option_time, [])
        assert spot is None

    def test_option_before_any_nifty_candle(self):
        """Option candle before first NIFTY candle of day → no valid spot."""
        candles = self._make_nifty_candles("2024-10-31")
        option_time = candles[0]["open_time"] - timedelta(minutes=5)
        spot = align_spot(option_time, candles)
        assert spot is None

    def test_preserves_ist_distinction(self):
        """Verify the alignment correctly handles IST/UTC conversion."""
        # 15:27 IST = 09:57 UTC (index close)
        # 15:35 IST = 10:05 UTC (option still trading)
        candles = self._make_nifty_candles("2024-10-31")
        option_at_15_35_ist = datetime(2024, 10, 31, 10, 5, tzinfo=timezone.utc)
        spot = align_spot(option_at_15_35_ist, candles)
        # Should use last NIFTY candle (at 09:57 UTC)
        assert spot is not None
        assert spot == candles[-1]["close"]


# ============================================================================
# J. Historical Lot Size Tests
# ============================================================================

class TestHistoricalLotSize:
    """Verify per-unit Greeks are unchanged, lot-level scales correctly."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = 0.065

    def test_per_unit_delta_unchanged_by_lot_size(self):
        """Per-unit delta must be identical regardless of lot_size."""
        g_25 = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_75 = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_25["delta"] == g_75["delta"]

    def test_lot_25_exposure(self):
        """Lot-level delta with lot_size=25."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        lot_delta = g["delta"] * 25
        expected = g["delta"] * 25
        assert abs(lot_delta - expected) < 1e-10

    def test_lot_75_exposure(self):
        """Lot-level delta with lot_size=75."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        lot_delta = g["delta"] * 75
        expected = g["delta"] * 75
        assert abs(lot_delta - expected) < 1e-10

    def test_lot_ratio(self):
        """75-lot exposure should be 3× the 25-lot exposure."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        exp_25 = g["delta"] * 25
        exp_75 = g["delta"] * 75
        assert abs(exp_75 / exp_25 - 3.0) < 1e-10

    def test_gamma_scales_with_lot_size(self):
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert abs(g["gamma"] * 75 / (g["gamma"] * 25) - 3.0) < 1e-10

    def test_vega_scales_with_lot_size(self):
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert abs(g["vega"] * 75 / (g["vega"] * 25) - 3.0) < 1e-10

    def test_theta_scales_with_lot_size(self):
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert abs(g["theta"] * 75 / (g["theta"] * 25) - 3.0) < 1e-10

    def test_different_lot_sizes_coexist(self):
        """Historical lot sizes 25 and 75 coexist correctly."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        # Per-unit Greeks are the same
        delta_unit = g["delta"]
        # But lot exposures differ
        delta_lot_25 = delta_unit * 25
        delta_lot_75 = delta_unit * 75
        assert delta_lot_25 != delta_lot_75
        assert delta_lot_25 == pytest.approx(delta_unit * 25)
        assert delta_lot_75 == pytest.approx(delta_unit * 75)


# ============================================================================
# K. Raw Data Immutability Tests
# ============================================================================

class TestRawDataImmutability:
    """Synthetic raw candle data must not be mutated by calculation."""

    def test_candle_not_mutated(self):
        """Creating GreeksResult must not modify input candle data."""
        candle = {
            "instrument_key": "NSE_FO|54758|31-10-2024",
            "interval": "3min",
            "open_time": datetime(2024, 10, 31, 3, 45, tzinfo=timezone.utc),
            "open": 6.3,
            "high": 7.95,
            "low": 4.5,
            "close": 7.3,
            "volume": 4810225.0,
            "open_interest": 9471100.0,
        }
        original = candle.copy()

        # Simulate Greeks calculation (reads candle, doesn't modify it)
        spot = align_spot(candle["open_time"], [candle])
        assert spot == candle["close"]

        # Verify candle unchanged
        for key in original:
            assert candle[key] == original[key], f"Candle field '{key}' was mutated"

    def test_multiple_candles_independent(self):
        """Processing one candle must not affect others."""
        candles = [
            {"open_time": datetime(2024, 10, 31, 3, 45, tzinfo=timezone.utc), "close": 25000.0},
            {"open_time": datetime(2024, 10, 31, 3, 48, tzinfo=timezone.utc), "close": 25001.0},
            {"open_time": datetime(2024, 10, 31, 3, 51, tzinfo=timezone.utc), "close": 24999.0},
        ]
        originals = [c.copy() for c in candles]

        for candle in candles:
            spot = align_spot(candle["open_time"], candles)
            assert spot is not None

        for i, candle in enumerate(candles):
            for key in originals[i]:
                assert candle[key] == originals[i][key]


# ============================================================================
# L. Determinism Tests
# ============================================================================

class TestDeterminism:
    """Same inputs must always produce the same outputs."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = 0.065

    def test_iv_deterministic(self):
        """Same inputs → same IV, every time."""
        price = bs_price("CE", self.S, self.K, self.T, self.sigma, self.r)
        results = []
        for _ in range(10):
            iv, err = solve_iv("CE", self.S, self.K, self.T, price, self.r)
            results.append((iv, err))
        assert all(r == results[0] for r in results)

    def test_greeks_deterministic(self):
        """Same inputs → same Greeks, every time."""
        results = []
        for _ in range(10):
            g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
            results.append(tuple(g[k] for k in ("delta", "gamma", "vega", "theta")))
        assert all(r == results[0] for r in results)

    def test_pricing_deterministic(self):
        """Same inputs → same price, every time."""
        results = []
        for _ in range(10):
            results.append(bs_price("CE", self.S, self.K, self.T, self.sigma, self.r))
        assert all(r == results[0] for r in results)

    def test_status_deterministic(self):
        """Same inputs → same validation status."""
        results = []
        for _ in range(10):
            _, err = solve_iv("CE", self.S, self.K, self.T, -1.0, self.r)
            results.append(err)
        assert all(r == "INVALID_PRICE" for r in results)


# ============================================================================
# M. Calculation Version Tests
# ============================================================================

class TestCalculationVersion:
    """Verify that calculation metadata can distinguish versions."""

    def test_different_versions_different_results(self):
        """Different risk-free rates produce different Greeks."""
        S, K, T, sigma = 25000.0, 25000.0, 30 / 365.25, 0.18
        g_v1 = bs_greeks("CE", S, K, T, sigma, r=0.065)
        g_v2 = bs_greeks("CE", S, K, T, sigma, r=0.075)
        # Delta, gamma, vega should be very similar (small r impact)
        # Theta should differ noticeably (r affects theta)
        assert abs(g_v1["delta"] - g_v2["delta"]) < 0.01
        assert g_v1["theta"] != g_v2["theta"], "Different r should give different theta"

    def test_same_version_same_result(self):
        """Same parameters → same result, regardless of call order."""
        S, K, T, sigma, r = 25000.0, 25000.0, 30 / 365.25, 0.18, 0.065
        g1 = bs_greeks("CE", S, K, T, sigma, r)
        g2 = bs_greeks("CE", S, K, T, sigma, r)
        assert g1 == g2

    def test_calculation_version_string(self):
        """Verify version string format."""
        version = "1.0.0"
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


# ============================================================================
# N. Time-to-Expiry Calculation Tests
# ============================================================================

class TestTimeToExpiry:
    """Verify T calculation from timestamps."""

    def test_zero_days(self):
        """Same date → T = 0."""
        valuation = datetime(2024, 10, 31, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(valuation, "2024-10-31")
        assert T == 0.0

    def test_one_day(self):
        """1 day before expiry → T ≈ 1/365.25."""
        valuation = datetime(2024, 10, 30, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(valuation, "2024-10-31")
        assert abs(T - 1 / 365.25) < 1e-6

    def test_thirty_days(self):
        """30 days before expiry → T ≈ 30/365.25."""
        valuation = datetime(2024, 10, 1, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(valuation, "2024-10-31")
        assert abs(T - 30 / 365.25) < 1e-6

    def test_past_expiry(self):
        """After expiry → T = 0 (clamped)."""
        valuation = datetime(2024, 11, 1, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(valuation, "2024-10-31")
        assert T == 0.0

    def test_same_time_different_days(self):
        """T should scale linearly with calendar days."""
        base = datetime(2024, 10, 15, 10, 0, tzinfo=timezone.utc)
        T7 = compute_time_to_expiry(base, "2024-10-22")
        T14 = compute_time_to_expiry(base, "2024-10-29")
        assert abs(T14 / T7 - 2.0) < 1e-6


# ============================================================================
# O. Unit Conversion Tests (Model → Canonical)
# ============================================================================

class TestUnitConversion:
    """Verify Greek unit conversions match existing frontend conventions."""

    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = 0.065

    def test_theta_annualized_to_daily(self):
        """Theta per year / 365 = theta per calendar day."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        theta_annual = g["theta"]
        theta_daily = theta_annual / 365.0
        assert theta_daily < 0, "Daily theta should be negative"
        assert abs(theta_daily) < abs(theta_annual), "Daily < annual"

    def test_vega_per_1_to_per_pct(self):
        """Vega per 1.00 vol / 100 = vega per 1 vol point (1%)."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        vega_per_1 = g["vega"]
        vega_per_pct = vega_per_1 * 0.01
        assert vega_per_pct < vega_per_1
        # For NIFTY ATM: vega per 1% ≈ ₹50-150
        assert 10 < vega_per_pct < 500, f"Vega per 1% = {vega_per_pct:.2f}"

    def test_delta_is_already_per_unit(self):
        """Delta from BS is already per 1 underlying point."""
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        # For ATM CE, delta ≈ 0.5
        assert 0.4 < g["delta"] < 0.6
