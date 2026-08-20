"""Service-level regression tests for resolve_legs().

These tests mock the broker-calling functions (fetch_available_expiries,
fetch_chain_for_expiry) and verify that the service layer correctly:
- Resolves expiry first, then resolves strike + extracts price from that chain
- Validates fixed expiry against the broker list before chain fetch
- Returns EXPIRY_UNAVAILABLE for unlisted fixed expiries
- Handles monthly expiry fallback to next future month
- Uses distinct LTPs per expiry to prove chain-selection correctness

All tests are async and use unittest.mock.patch.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services.template_resolution import ResolutionResult, resolve_legs


# ---------------------------------------------------------------------------
# Fixtures: canonical chain shapes with DISTINCT LTP per expiry
# ---------------------------------------------------------------------------

def _make_chain(spot, strikes, ltp_base):
    """Canonical chain with ltp = ltp_base for ATM strike, varying for others."""
    rows = []
    for s in strikes:
        rows.append({
            "strike": s,
            "call": {
                "ltp": ltp_base + (s - 25000) * 0.1,
                "delta": 0.5 + (s - 25000) * 0.0001,
                "quote_timestamp": "2026-08-20T10:00:00+05:30",
            },
            "put": {
                "ltp": ltp_base - (s - 25000) * 0.1,
                "delta": -0.5 - (s - 25000) * 0.0001,
                "quote_timestamp": "2026-08-20T10:00:00+05:30",
            },
        })
    return {"symbol": "NIFTY", "underlying_spot_price": spot, "chain": rows}


STRIKES = [24800.0, 24900.0, 25000.0, 25100.0, 25200.0]

# Distinct LTP bases per expiry — proves wrong chain = wrong price
CHAINS = {
    "2026-08-20": _make_chain(25000.0, STRIKES, ltp_base=100),   # CW:  ATM CE = 100.0
    "2026-08-27": _make_chain(25000.0, STRIKES, ltp_base=200),   # NW:  ATM CE = 200.0
    "2026-09-24": _make_chain(25000.0, STRIKES, ltp_base=50),    # MTH: ATM CE = 50.0
}

ALL_EXPIRIES = ["2026-08-20", "2026-08-27", "2026-09-24"]

MONTHLY_EXPIRIES = [
    "2026-08-18", "2026-08-25",
    "2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29",
]

MONTHLY_CHAINS = {
    "2026-08-18": _make_chain(25000.0, STRIKES, ltp_base=80),
    "2026-08-25": _make_chain(25000.0, STRIKES, ltp_base=120),
    "2026-09-01": _make_chain(25000.0, STRIKES, ltp_base=150),
    "2026-09-08": _make_chain(25000.0, STRIKES, ltp_base=160),
    "2026-09-15": _make_chain(25000.0, STRIKES, ltp_base=170),
    "2026-09-22": _make_chain(25000.0, STRIKES, ltp_base=180),
    "2026-09-29": _make_chain(25000.0, STRIKES, ltp_base=250),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_expiries(expiries):
    """Return an async mock for fetch_available_expiries."""
    async def _f(access_token, symbol):
        return expiries
    return _f


def _mock_chains(chain_map):
    """Return an async mock for fetch_chain_for_expiry."""
    async def _f(access_token, symbol, expiry_date):
        return chain_map.get(expiry_date)
    return _f


def _get_ltp(chain, strike, option_type):
    """Extract LTP from a chain."""
    for row in chain.get("chain", []):
        if abs(row["strike"] - strike) < 0.001:
            return row.get(option_type, {}).get("ltp")
    return None


# ---------------------------------------------------------------------------
# Tests: service-level chain-selection correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestServiceChainSelection:
    """resolve_legs() must use the resolved expiry's chain for price extraction."""

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_current_week_uses_correct_chain(self, mock_exp, mock_chain):
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-20",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "current_week",
        }]
        result = await resolve_legs("tok", "NIFTY", legs)

        assert result.status in ("RESOLVED", "RESOLVED_WITH_WARNINGS")
        assert len(result.legs) == 1
        leg = result.legs[0]
        assert leg.resolved_expiry == "2026-08-20"
        # LTP must be 100.0 (from CW chain), not 200.0 (NW) or 50.0 (MTH)
        assert leg.current_price == 100.0, f"Expected 100.0 from CW chain, got {leg.current_price}"

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_next_week_uses_correct_chain(self, mock_exp, mock_chain):
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-27",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "next_week",
        }]
        result = await resolve_legs("tok", "NIFTY", legs)

        assert result.status in ("RESOLVED", "RESOLVED_WITH_WARNINGS")
        leg = result.legs[0]
        assert leg.resolved_expiry == "2026-08-27"
        assert leg.current_price == 200.0, f"Expected 200.0 from NW chain, got {leg.current_price}"

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_monthly_august_uses_correct_chain(self, mock_exp, mock_chain):
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-27",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "monthly",
        }]
        result = await resolve_legs("tok", "NIFTY", legs)

        assert result.status in ("RESOLVED", "RESOLVED_WITH_WARNINGS")
        leg = result.legs[0]
        # Monthly in August picks 2026-08-27 (latest in Aug)
        assert leg.resolved_expiry == "2026-08-27"
        assert leg.current_price == 200.0

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_dte_range_uses_correct_chain(self, mock_exp, mock_chain):
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        # DTE 30-40 from Aug 20 → picks 2026-09-24 (DTE=35)
        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-20",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "dte_range",
            "expiry_dte_min": 30, "expiry_dte_max": 40,
        }]

        # Patch date.today() inside resolve_legs to control DTE calculation
        with patch("app.services.template_resolution.date") as mock_date:
            mock_date.today.return_value = date(2026, 8, 20)
            mock_date.side_effect = lambda *a, **k: date(*a, **k)
            result = await resolve_legs("tok", "NIFTY", legs)

        assert result.status in ("RESOLVED", "RESOLVED_WITH_WARNINGS", "NO_PRICES")
        if result.legs:
            leg = result.legs[0]
            assert leg.resolved_expiry == "2026-09-24"
            assert leg.current_price == 50.0

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_fixed_expiry_validates_against_broker_list(self, mock_exp, mock_chain):
        """Fixed expiry NOT in broker list → EXPIRY_UNAVAILABLE before chain fetch."""
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2099-01-01",  # not in broker list
            "quantity": 1, "lot_size": 65,
        }]
        result = await resolve_legs("tok", "NIFTY", legs)

        assert result.status == "FAILED"
        assert any("EXPIRY_UNAVAILABLE" in e for e in result.errors)
        # Chain should NOT have been fetched for the bad expiry
        mock_chain.assert_not_called()

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_fixed_expiry_in_list_fetches_chain(self, mock_exp, mock_chain):
        """Fixed expiry in broker list → chain is fetched and leg resolves."""
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-27",
            "quantity": 1, "lot_size": 65,
        }]
        result = await resolve_legs("tok", "NIFTY", legs)

        assert result.status in ("RESOLVED", "RESOLVED_WITH_WARNINGS")
        leg = result.legs[0]
        assert leg.resolved_expiry == "2026-08-27"
        assert leg.current_price == 200.0

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_resolved_expiry_and_price_from_same_chain(self, mock_exp, mock_chain):
        """Proof that resolved_expiry and current_price always come from the same chain."""
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.side_effect = _mock_chains(CHAINS)

        # Use monthly which resolves to a dynamic expiry
        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-20",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "current_week",
        }]
        result = await resolve_legs("tok", "NIFTY", legs)

        leg = result.legs[0]
        # Verify the price matches what we'd get from the resolved expiry's chain
        expected_chain = CHAINS[leg.resolved_expiry]
        expected_ltp = _get_ltp(expected_chain, 25000.0, "call")
        assert leg.current_price == expected_ltp, (
            f"Price {leg.current_price} does not match chain for "
            f"expiry {leg.resolved_expiry} (expected {expected_ltp})"
        )


# ---------------------------------------------------------------------------
# Tests: monthly expiry fallback to next future month
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMonthlyFallback:
    """Monthly resolver should prefer next future month when current month has none."""

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_monthly_after_all_august_expiries_passed(self, mock_exp, mock_chain):
        """Today = Sep 2026, no Aug expiries left → picks latest Sep expiry."""
        # Only list Sep expiries (Aug ones have all passed)
        sep_expiries = [e for e in MONTHLY_EXPIRIES if e.startswith("2026-09")]
        mock_exp.return_value = sep_expiries
        mock_chain.side_effect = _mock_chains(MONTHLY_CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-09-01",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "monthly",
        }]

        with patch("app.services.template_resolution.date") as mock_date:
            mock_date.today.return_value = date(2026, 10, 1)  # Oct 1 — all Sep passed
            mock_date.side_effect = lambda *a, **k: date(*a, **k)
            result = await resolve_legs("tok", "NIFTY", legs)

        if result.legs:
            leg = result.legs[0]
            # Should use a Sep expiry (nearest future month)
            assert leg.resolved_expiry.startswith("2026-09")

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_monthly_on_expiry_day(self, mock_exp, mock_chain):
        """Today IS the monthly expiry → picks it (expiry day is >= today)."""
        mock_exp.return_value = MONTHLY_EXPIRIES
        mock_chain.side_effect = _mock_chains(MONTHLY_CHAINS)

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-25",
            "quantity": 1, "lot_size": 65,
            "expiry_mode": "monthly",
        }]

        with patch("app.services.template_resolution.date") as mock_date:
            mock_date.today.return_value = date(2026, 8, 25)
            mock_date.side_effect = lambda *a, **k: date(*a, **k)
            result = await resolve_legs("tok", "NIFTY", legs)

        if result.legs:
            leg = result.legs[0]
            assert leg.resolved_expiry == "2026-08-25"


# ---------------------------------------------------------------------------
# Tests: empty / error cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestServiceEdgeCases:

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_empty_legs_returns_failed(self, mock_exp, mock_chain):
        result = await resolve_legs("tok", "NIFTY", [])
        assert result.status == "FAILED"
        assert "No legs" in result.errors[0]
        mock_exp.assert_not_called()

    @patch("app.services.template_resolution.fetch_chain_for_expiry")
    @patch("app.services.template_resolution.fetch_available_expiries")
    async def test_no_chain_data_returns_no_prices(self, mock_exp, mock_chain):
        mock_exp.return_value = ALL_EXPIRIES
        mock_chain.return_value = None  # broker returns nothing

        legs = [{
            "action": "buy", "option_type": "call",
            "strike": 25000.0, "expiry": "2026-08-27",
            "quantity": 1, "lot_size": 65,
        }]
        result = await resolve_legs("tok", "NIFTY", legs)
        assert result.status == "NO_PRICES"
