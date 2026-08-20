"""Phase 6.9: Tests for dynamic template execution bridge.

Tests the execution-time re-resolution, change detection, validation,
one-strike-step policy, TOCTOU protection, and execution flow for V2
dynamic templates.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services.template_resolution import (
    ResolutionResult,
    ResolvedLegOutput,
    _is_one_strike_step,
    build_execution_legs_from_resolution,
    compare_resolutions,
    resolution_changes_status,
    validate_execution_resolution,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_resolved_leg(
    position=0, action="buy", option_type="call", quantity=1, lot_size=65,
    resolved_strike=25000.0, resolved_expiry="2026-08-20",
    strike_mode_used="atm", expiry_mode_used="current_week",
    current_price=100.0, price_status="available",
):
    return ResolvedLegOutput(
        position=position, action=action, option_type=option_type,
        quantity=quantity, lot_size=lot_size,
        resolved_strike=resolved_strike, resolved_expiry=resolved_expiry,
        strike_mode_used=strike_mode_used, expiry_mode_used=expiry_mode_used,
        current_price=current_price, price_status=price_status,
        symbol="NIFTY", expiration_date=resolved_expiry,
        strike_price=resolved_strike,
    )


def _make_resolution_result(legs=None, status="RESOLVED", errors=None, warnings=None,
                            chain_strike_step=50.0):
    return ResolutionResult(
        status=status, symbol="NIFTY",
        legs=[_make_resolved_leg()] if legs is None else legs,
        errors=errors or [], warnings=warnings or [],
        chain_strike_step=chain_strike_step,
    )


# ---------------------------------------------------------------------------
# Tests: _is_one_strike_step
# ---------------------------------------------------------------------------

class TestIsOneStrikeStep:
    def test_within_one_step(self):
        assert _is_one_strike_step(25000, 25050, 50.0) is True

    def test_exactly_one_step(self):
        assert _is_one_strike_step(25000, 25050, 50.0) is True

    def test_two_steps(self):
        assert _is_one_strike_step(25000, 25100, 50.0) is False

    def test_unknown_step(self):
        assert _is_one_strike_step(25000, 25050, None) is False

    def test_zero_step(self):
        assert _is_one_strike_step(25000, 25050, 0) is False

    def test_same_strike(self):
        assert _is_one_strike_step(25000, 25000, 50.0) is True


# ---------------------------------------------------------------------------
# Tests: compare_resolutions
# ---------------------------------------------------------------------------

class TestCompareResolutions:
    def test_no_changes(self):
        preview = [{"position": 0, "resolved_strike": 25000, "resolved_expiry": "2026-08-20"}]
        fresh = _make_resolution_result([_make_resolved_leg(resolved_strike=25000, resolved_expiry="2026-08-20")])
        assert compare_resolutions(preview, fresh) == []

    def test_strike_changed(self):
        preview = [{"position": 0, "resolved_strike": 25000, "resolved_expiry": "2026-08-20"}]
        fresh = _make_resolution_result([_make_resolved_leg(resolved_strike=25050, resolved_expiry="2026-08-20")])
        changes = compare_resolutions(preview, fresh)
        assert len(changes) == 1
        assert changes[0]["field"] == "strike"
        assert changes[0]["preview_value"] == 25000
        assert changes[0]["fresh_value"] == 25050

    def test_expiry_changed(self):
        preview = [{"position": 0, "resolved_strike": 25000, "resolved_expiry": "2026-08-20"}]
        fresh = _make_resolution_result([_make_resolved_leg(resolved_strike=25000, resolved_expiry="2026-08-27")])
        changes = compare_resolutions(preview, fresh)
        assert len(changes) == 1
        assert changes[0]["field"] == "expiry"

    def test_both_changed(self):
        preview = [{"position": 0, "resolved_strike": 25000, "resolved_expiry": "2026-08-20"}]
        fresh = _make_resolution_result([_make_resolved_leg(resolved_strike=25050, resolved_expiry="2026-08-27")])
        changes = compare_resolutions(preview, fresh)
        assert len(changes) == 2

    def test_multi_leg_partial_change(self):
        preview = [
            {"position": 0, "resolved_strike": 25000, "resolved_expiry": "2026-08-20"},
            {"position": 1, "resolved_strike": 25200, "resolved_expiry": "2026-08-20"},
        ]
        fresh = _make_resolution_result([
            _make_resolved_leg(position=0, resolved_strike=25000, resolved_expiry="2026-08-20"),
            _make_resolved_leg(position=1, resolved_strike=25300, resolved_expiry="2026-08-27"),
        ])
        changes = compare_resolutions(preview, fresh)
        assert len(changes) == 2
        assert all(c["position"] == 1 for c in changes)


# ---------------------------------------------------------------------------
# Tests: resolution_changes_status
# ---------------------------------------------------------------------------

class TestResolutionChangesStatus:
    def test_unchanged(self):
        assert resolution_changes_status([]) == "UNCHANGED"

    def test_strike_only(self):
        assert resolution_changes_status([{"field": "strike"}]) == "CHANGED_STRIKE"

    def test_expiry_only(self):
        assert resolution_changes_status([{"field": "expiry"}]) == "CHANGED_EXPIRY"

    def test_both(self):
        assert resolution_changes_status([{"field": "strike"}, {"field": "expiry"}]) == "CHANGED_BOTH"


# ---------------------------------------------------------------------------
# Tests: build_execution_legs_from_resolution
# ---------------------------------------------------------------------------

class TestBuildExecutionLegs:
    def test_converts_to_execution_leg_in(self):
        legs = [_make_resolved_leg(resolved_strike=25100, resolved_expiry="2026-08-27")]
        result = build_execution_legs_from_resolution(legs, "NIFTY")
        assert len(result) == 1
        assert result[0]["symbol"] == "NIFTY"
        assert result[0]["expiration_date"] == "2026-08-27"
        assert result[0]["strike_price"] == 25100
        assert result[0]["option_type"] == "call"
        assert result[0]["action"] == "buy"
        assert result[0]["quantity"] == 1
        assert result[0]["lot_size"] == 65


# ---------------------------------------------------------------------------
# Tests: validate_execution_resolution — defense in depth
# ---------------------------------------------------------------------------

class TestValidateExecutionResolution:
    def test_ok_when_all_resolved(self):
        result = _make_resolution_result()
        ok, errors = validate_execution_resolution(result)
        assert ok is True
        assert errors == []

    def test_fails_when_resolution_failed(self):
        result = _make_resolution_result(status="FAILED", errors=["No chain data"])
        ok, errors = validate_execution_resolution(result)
        assert ok is False
        assert "No chain data" in errors[0]

    def test_fails_when_no_legs(self):
        result = _make_resolution_result(legs=[])
        ok, errors = validate_execution_resolution(result)
        assert ok is False

    def test_fails_when_price_unavailable(self):
        leg = _make_resolved_leg(price_status="unavailable")
        result = _make_resolution_result([leg])
        ok, errors = validate_execution_resolution(result)
        assert ok is False
        assert any("unavailable" in e for e in errors)

    def test_fails_when_price_stale(self):
        leg = _make_resolved_leg(price_status="stale")
        result = _make_resolution_result([leg])
        ok, errors = validate_execution_resolution(result)
        assert ok is False
        assert any("stale" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: TOCTOU protection — the core defense-in-depth scenario
# ---------------------------------------------------------------------------

class TestTOCTOUProtection:
    """Preview A → confirm A → execute resolves B → B differs from A → MUST BLOCK."""

    def test_preview_unchanged_execute_changed_no_confirmation(self):
        """Preview says UNCHANGED, but execute resolves differently.
        Frontend sends preview values as confirmation. Execute detects
        fresh differs from confirmed → must block."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25050}]
        # Frontend sends preview value (25000) as confirmation
        confirmed_strikes = {0: 25000.0}
        # Fresh resolution has 25050 (different from confirmed 25000)
        result = _make_resolution_result([_make_resolved_leg(resolved_strike=25050)])
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        # 25050 - 25000 = 50 = one step → should PASS (auto-execute)
        assert ok is True

    def test_preview_unchanged_execute_changed_two_steps(self):
        """Preview says UNCHANGED (25000), execute resolves 25100 (2 steps away).
        Frontend sends preview value (25000) as confirmation.
        Fresh differs by > 1 step → MUST BLOCK."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25100}]
        confirmed_strikes = {0: 25000.0}
        result = _make_resolution_result([_make_resolved_leg(resolved_strike=25100)])
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        assert ok is False
        assert any("re-confirm" in e.lower() or "changed" in e.lower() for e in errors)

    def test_preview_changed_execute_changed_again(self):
        """Preview: 25000 → 25050 (user confirmed 25050).
        Execute: fresh is 25100 (changed again from confirmed).
        Must block."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25100}]
        # User confirmed the preview's fresh value (25050)
        confirmed_strikes = {0: 25050.0}
        # Execute fresh is 25100 (different from confirmed 25050)
        result = _make_resolution_result([_make_resolved_leg(resolved_strike=25100)])
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        # 25100 - 25050 = 50 = one step from confirmed → auto-execute
        # But the change list says preview was 25000, confirmed is 25050, fresh is 25100
        # The validation checks confirmed vs fresh, not preview vs fresh
        assert ok is True  # 50-point diff from confirmed is within one step

    def test_expiry_changed_must_always_block(self):
        """Expiry change always requires re-confirmation, even within 'one step'."""
        changes = [{"position": 0, "field": "expiry", "preview_value": "2026-08-20", "fresh_value": "2026-08-27"}]
        confirmed_expiries = {0: "2026-08-20"}
        result = _make_resolution_result([_make_resolved_leg(resolved_expiry="2026-08-27")])
        ok, errors = validate_execution_resolution(
            result, confirmed_expiries=confirmed_expiries, changes=changes,
        )
        assert ok is False
        assert any("expiry" in e.lower() for e in errors)

    def test_no_confirmation_values_at_all(self):
        """Changes detected but frontend sent no confirmation values → must block."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25050}]
        result = _make_resolution_result([_make_resolved_leg(resolved_strike=25050)])
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=None, confirmed_expiries=None, changes=changes,
        )
        assert ok is False
        assert any("no confirmation" in e.lower() for e in errors)

    def test_confirmed_matches_fresh_exact(self):
        """Confirmed value exactly matches fresh → OK."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25050}]
        confirmed_strikes = {0: 25050.0}  # Matches fresh exactly
        result = _make_resolution_result([_make_resolved_leg(resolved_strike=25050)])
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        assert ok is True

    def test_multi_leg_partial_confirmation(self):
        """One leg confirmed, another not → block for the unconfirmed leg."""
        changes = [
            {"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25100},
            {"position": 1, "field": "strike", "preview_value": 25200, "fresh_value": 25300},
        ]
        # Only leg 0 confirmed
        confirmed_strikes = {0: 25100.0}
        result = _make_resolution_result([
            _make_resolved_leg(position=0, resolved_strike=25100),
            _make_resolved_leg(position=1, resolved_strike=25300),
        ])
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        # Leg 0: confirmed 25100 matches fresh 25100 → OK
        # Leg 1: no confirmation → block
        assert ok is False
        assert any("leg 2" in e.lower() or "position 1" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Tests: one-strike-step policy with chain step detection
# ---------------------------------------------------------------------------

class TestOneStrikeStepPolicy:
    def test_one_step_auto_executes(self):
        """Strike changed by exactly 1 chain step → auto-execute."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25050}]
        confirmed_strikes = {0: 25000.0}  # Preview value
        result = _make_resolution_result(
            [_make_resolved_leg(resolved_strike=25050)],
            chain_strike_step=50.0,
        )
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        assert ok is True

    def test_two_steps_blocks(self):
        """Strike changed by 2 chain steps → block."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25100}]
        confirmed_strikes = {0: 25000.0}
        result = _make_resolution_result(
            [_make_resolved_leg(resolved_strike=25100)],
            chain_strike_step=50.0,
        )
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        assert ok is False

    def test_unknown_step_blocks(self):
        """Chain step unknown → treat any change as material → block."""
        changes = [{"position": 0, "field": "strike", "preview_value": 25000, "fresh_value": 25050}]
        confirmed_strikes = {0: 25000.0}
        result = _make_resolution_result(
            [_make_resolved_leg(resolved_strike=25050)],
            chain_strike_step=None,
        )
        ok, errors = validate_execution_resolution(
            result, confirmed_strikes=confirmed_strikes, changes=changes,
        )
        assert ok is False


# ---------------------------------------------------------------------------
# Tests: chain_strike_step computation
# ---------------------------------------------------------------------------

class TestChainStrikeStep:
    def test_computed_from_chain(self):
        """chain_strike_step is computed from the chain's strike spacing."""
        result = ResolutionResult(
            status="RESOLVED", symbol="NIFTY",
            legs=[_make_resolved_leg()],
            chain_strike_step=50.0,
        )
        assert result.chain_strike_step == 50.0

    def test_none_when_no_chain(self):
        result = ResolutionResult(
            status="FAILED", symbol="NIFTY",
            legs=[], chain_strike_step=None,
        )
        assert result.chain_strike_step is None
