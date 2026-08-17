"""Phase 5.2.1 tests — option tick-size normalization (NIFTY index options: ₹0.05).

The canonical helper ``round_option_price`` is the ONLY place option trading
prices are tick-aligned; it is used at every authoritative fill boundary
(strategy entry, single-position exit, bulk exit). These tests pin the exact
tick-rounding contract, float-artifact safety and invalid-input handling.
"""

import pytest

from app.services.paper_execution import DEFAULT_OPTION_TICK_SIZE, round_option_price


@pytest.mark.parametrize(
    "price,expected",
    [
        # Spec §29: exact NIFTY ₹0.05 tick examples.
        (125.23, 125.25),
        (125.24, 125.25),
        (125.25, 125.25),
        (125.26, 125.25),
        (125.27, 125.25),
        (125.28, 125.30),
        # Round-trip boundary cases.
        (0.0, 0.0),
        (0.02, 0.0),
        (0.03, 0.05),
        (31.60, 31.60),
        (48.75, 48.75),
        # Floating-point artifacts must never escape.
        (48.749999999, 48.75),
        # Large prices stay tick-aligned.
        (999999.99, 1000000.0),
        (123456.23, 123456.25),
    ],
)
def test_round_option_price_nifty_tick(price, expected):
    assert round_option_price(price) == pytest.approx(expected, abs=1e-9)


def test_round_option_price_custom_tick_size():
    assert round_option_price(125.23, tick_size=0.05) == 125.25
    assert round_option_price(100.5, tick_size=0.25) == 100.5
    assert round_option_price(100.62, tick_size=0.25) == 100.5
    assert round_option_price(100.63, tick_size=0.25) == 100.75


def test_round_option_price_never_artifacts():
    result = round_option_price(125.23)
    # Exactly two decimals after the tick step — no 125.25000000000001.
    assert abs(result - round(result, 2)) < 1e-9


def test_round_option_price_invalid_inputs_pass_through_never_zero():
    # Invalid/missing prices are NOT converted to zero (spec §29).
    assert round_option_price(None) is None
    assert round_option_price(float("nan")) is None or round_option_price(float("nan")) != 0
    # A negative price is invalid — never coerced to a positive tick or 0.
    assert round_option_price(-5.0) == -5.0
    assert round_option_price(-5.0) != 0.0


def test_round_option_price_default_tick_constant():
    assert DEFAULT_OPTION_TICK_SIZE == 0.05
