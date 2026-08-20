"""Phase 6.8A: Dynamic Strategy Resolver Foundation.

Pure, testable functions that resolve formula-based leg specifications against
live option chain data.  Every function is deterministic, stateless, and
independent of FastAPI / database / broker adapters — callers feed in the
canonical chain shape produced by ``transform_chain`` and the resolver
returns concrete strike + expiry + validation feedback.

Strike modes
    fixed       — absolute numeric strike (Phase 6.7 backward-compat)
    atm         — nearest listed strike to the underlying spot
    atm_offset_steps — ATM strike shifted by N strike-index steps
    atm_offset  — ATM strike shifted by an absolute rupee amount
    spot_offset — spot price shifted by an absolute rupee amount, normalised
    delta       — strike whose broker-reported delta is nearest to a target

Expiry modes
    fixed       — literal YYYY-MM-DD string
    current_week  — nearest listed expiry on or after today
    next_week     — second-nearest listed expiry on or after today
    monthly       — latest listed expiry in the current calendar month
    dte_range     — listed expiry whose days-to-expiry falls in [min, max]

All expiry modes use the broker-provided listed expiry dates as the
sole source of truth.  No specific weekday (Tuesday, Thursday, etc.)
is assumed.  Holiday handling is naturally provided by the broker
omitting holiday dates from its listed expiries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal


# ============================================================================
# Enums
# ============================================================================

class StrikeMode(str, Enum):
    FIXED = "fixed"
    ATM = "atm"
    ATM_OFFSET_STEPS = "atm_offset_steps"
    ATM_OFFSET = "atm_offset"
    SPOT_OFFSET = "spot_offset"
    DELTA = "delta"


class ExpiryMode(str, Enum):
    FIXED = "fixed"
    CURRENT_WEEK = "current_week"
    NEXT_WEEK = "next_week"
    MONTHLY = "monthly"
    DTE_RANGE = "dte_range"


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class LegFormula:
    """One leg's formula specification (the *input* to the resolver).

    For fixed-leg templates (Phase 6.7 backward-compat) set ``strike_mode``
    to ``"fixed"`` and populate ``strike`` / ``expiry`` directly.  For
    dynamic legs populate the appropriate anchor fields.
    """
    action: Literal["buy", "sell"]
    option_type: Literal["call", "put"]
    quantity: int
    lot_size: int

    # Strike specification
    strike_mode: StrikeMode = StrikeMode.FIXED
    strike: float | None = None          # fixed mode
    strike_offset: float | None = None   # atm_offset / spot_offset (rupees)
    strike_offset_steps: int | None = None  # atm_offset_steps (int steps)
    target_delta: float | None = None    # delta mode (CE ≈ +, PE ≈ −)

    # Expiry specification
    expiry_mode: ExpiryMode = ExpiryMode.FIXED
    expiry: str | None = None            # fixed mode (YYYY-MM-DD)
    expiry_dte_min: int | None = None    # dte_range mode
    expiry_dte_max: int | None = None    # dte_range mode


@dataclass
class ResolvedLeg:
    """One resolved, executable leg (the *output* of the resolver).

    Contains enough information for the existing paper execution engine to
    consume it without any second execution system — ``to_execution_leg()``
    produces exactly the ``ExecutionLegIn`` shape.
    """
    # Resolved values
    resolved_strike: float
    resolved_expiry: str   # YYYY-MM-DD

    # Echoed from formula
    action: str
    option_type: str
    quantity: int
    lot_size: int

    # Diagnostic: what the resolver did
    strike_mode_used: str
    expiry_mode_used: str
    anchor_value: float | None = None   # ATM or spot value used
    delta_actual: float | None = None   # actual delta of selected option

    # Feedback
    warnings: list[str] = field(default_factory=list)

    def to_execution_leg(self, symbol: str) -> dict:
        """Produce the ``ExecutionLegIn`` shape the paper engine expects."""
        return {
            "symbol": symbol,
            "expiration_date": self.resolved_expiry,
            "strike_price": self.resolved_strike,
            "option_type": self.option_type,
            "action": self.action,
            "quantity": self.quantity,
            "lot_size": self.lot_size,
        }


@dataclass
class ResolverResult:
    """Aggregated result for resolving one leg formula."""
    leg: ResolvedLeg | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.leg is not None and len(self.errors) == 0


# ============================================================================
# Chain helpers (pure, operating on the canonical transform_chain shape)
# ============================================================================

def sorted_strikes(chain_rows: list[dict]) -> list[float]:
    """Extract and sort strike prices from canonical chain rows."""
    return sorted(r["strike"] for r in chain_rows)


def chain_row_by_strike(chain_rows: list[dict]) -> dict[float, dict]:
    """Map strike → chain row for O(1) lookups."""
    return {r["strike"]: r for r in chain_rows}


def spot_price(chain_response: dict) -> float | None:
    """Extract the underlying spot from a canonical chain response."""
    return chain_response.get("underlying_spot_price")


def chain_rows(chain_response: dict) -> list[dict]:
    """Extract the chain rows list from a canonical chain response."""
    return chain_response.get("chain", [])


# ============================================================================
# Strike resolution functions
# ============================================================================

def nearest_strike_index(strikes: list[float], target: float) -> int:
    """Index of the strike closest to *target*.

    Returns 0 for empty lists or missing target (safe fallback).
    Ties go to the lower index (lower strike), matching the frontend.
    """
    if not strikes or target is None:
        return 0
    best = 0
    best_diff = abs(strikes[0] - target)
    for i in range(1, len(strikes)):
        diff = abs(strikes[i] - target)
        if diff < best_diff:
            best_diff = diff
            best = i
    return best


def resolve_atm(strikes: list[float], spot: float) -> float:
    """ATM strike: nearest listed strike to the underlying spot.

    Raises ValueError when *strikes* is empty or *spot* is None.
    """
    if not strikes:
        raise ValueError("Cannot resolve ATM: chain has no strikes.")
    if spot is None:
        raise ValueError("Cannot resolve ATM: spot price is unavailable.")
    return strikes[nearest_strike_index(strikes, spot)]


def resolve_fixed_strike(strikes: list[float], target: float) -> tuple[float, list[str]]:
    """Validate and return a fixed strike.

    The chain's listed strikes are authoritative.  If the exact requested
    strike is not in the chain, a blocking ``STRIKE_UNAVAILABLE`` error is
    raised — the resolver does NOT silently clamp to the nearest strike.

    Dynamic modes (atm, atm_offset, spot_offset, etc.) may continue
    normalising to the nearest listed strike because they express a
    *relative* intent that inherently resolves to the closest available.
    """
    if target is None:
        raise ValueError("Fixed strike requires a numeric value.")
    if not strikes:
        raise ValueError("Cannot validate fixed strike: chain has no strikes.")
    if target in strikes:
        return target, []
    raise ValueError(
        f"STRIKE_UNAVAILABLE: Strike {target:g} is not listed. "
        f"Available: {', '.join(f'{s:g}' for s in strikes)}"
    )


def resolve_atm_offset_steps(
    strikes: list[float], spot: float, steps: int,
) -> tuple[float, list[str]]:
    """ATM + N strike-index steps.

    Steps are clamped to the chain boundary.  A warning is emitted when
    clamping occurs.
    """
    if not strikes:
        raise ValueError("Cannot resolve ATM offset steps: chain has no strikes.")
    if spot is None:
        raise ValueError("Cannot resolve ATM offset steps: spot price is unavailable.")
    if steps is None:
        raise ValueError("Steps value is required.")

    atm_idx = nearest_strike_index(strikes, spot)
    target_idx = atm_idx + steps
    warnings: list[str] = []

    if target_idx < 0:
        warnings.append(
            f"ATM offset {steps} steps would go below the chain; "
            f"clamped to index 0 (strike {strikes[0]:g})."
        )
        target_idx = 0
    elif target_idx >= len(strikes):
        warnings.append(
            f"ATM offset {steps} steps would exceed the chain ({len(strikes)} strikes); "
            f"clamped to index {len(strikes) - 1} (strike {strikes[-1]:g})."
        )
        target_idx = len(strikes) - 1

    return strikes[target_idx], warnings


def resolve_atm_offset(
    strikes: list[float], spot: float, offset: float,
) -> tuple[float, list[str]]:
    """ATM strike shifted by an absolute rupee amount, normalised to a
    listed strike.

    ``offset`` can be positive (above ATM) or negative (below ATM).
    """
    if not strikes:
        raise ValueError("Cannot resolve ATM offset: chain has no strikes.")
    if spot is None:
        raise ValueError("Cannot resolve ATM offset: spot price is unavailable.")
    if offset is None:
        raise ValueError("Offset value is required.")

    atm = resolve_atm(strikes, spot)
    target = atm + offset
    idx = nearest_strike_index(strikes, target)
    resolved = strikes[idx]
    warnings: list[str] = []
    if resolved != target:
        warnings.append(
            f"ATM offset {offset:+g} targets {target:g}; "
            f"normalised to nearest listed strike {resolved:g}."
        )
    return resolved, warnings


def resolve_spot_offset(
    strikes: list[float], spot: float, offset: float,
) -> tuple[float, list[str]]:
    """Spot price shifted by an absolute rupee amount, normalised to a
    listed strike.
    """
    if not strikes:
        raise ValueError("Cannot resolve spot offset: chain has no strikes.")
    if spot is None:
        raise ValueError("Cannot resolve spot offset: spot price is unavailable.")
    if offset is None:
        raise ValueError("Offset value is required.")

    target = spot + offset
    idx = nearest_strike_index(strikes, target)
    resolved = strikes[idx]
    warnings: list[str] = []
    if resolved != target:
        warnings.append(
            f"Spot offset {offset:+g} targets {target:g}; "
            f"normalised to nearest listed strike {resolved:g}."
        )
    return resolved, warnings


def resolve_delta_target(
    chain_rows: list[dict],
    option_type: str,
    target_delta: float,
    spot: float | None = None,
) -> tuple[dict, float, list[str]]:
    """Find the chain row whose broker-reported delta is nearest to
    *target_delta* for the given option type.

    Returns ``(row, actual_delta, warnings)``.

    Delta sign conventions (from Upstox broker feed):
        CE (call): delta ∈ [0, +1]   — target ≈ +0.30
        PE (put):  delta ∈ [−1, 0]   — target ≈ −0.30

    When multiple strikes have equal delta distance, the one closest to
    ATM (nearest to *spot*) is selected.

    Raises ValueError when no chain rows have a usable delta.
    """
    if not chain_rows:
        raise ValueError("Cannot resolve delta target: chain has no rows.")
    if target_delta is None:
        raise ValueError("Target delta is required.")
    if option_type not in ("call", "put"):
        raise ValueError(
            f"INVALID_OPTION_TYPE: option_type must be 'call' or 'put', "
            f"got '{option_type}'."
        )

    side = option_type
    candidates: list[dict] = []

    for row in chain_rows:
        quote = row.get(side) or {}
        delta = quote.get("delta")
        if delta is None:
            continue
        candidates.append({
            "row": row,
            "delta": delta,
            "diff": abs(delta - target_delta),
        })

    if not candidates:
        raise ValueError(
            f"Greeks data is not available for {option_type} options "
            f"in this chain."
        )

    # Sort by delta distance, then by closeness to ATM as tiebreaker
    if spot is not None and candidates:
        atm_strike = resolve_atm(sorted_strikes(chain_rows), spot)
        for c in candidates:
            c["atm_distance"] = abs(c["row"]["strike"] - atm_strike)
    else:
        for c in candidates:
            c["atm_distance"] = 0

    candidates.sort(key=lambda c: (c["diff"], c["atm_distance"]))
    best = candidates[0]
    warnings: list[str] = []

    # Warn when the best match is far from the target
    if best["diff"] > 0.20:
        raise ValueError(
            f"Delta target {target_delta:+.2f} is unreachable; "
            f"closest available is {best['delta']:+.2f} "
            f"(strike {best['row']['strike']:g})."
        )
    if best["diff"] > 0.10:
        warnings.append(
            f"Delta target {target_delta:+.2f} is approximate; "
            f"closest available is {best['delta']:+.2f} "
            f"(strike {best['row']['strike']:g})."
        )

    return best["row"], best["delta"], warnings


# ============================================================================
# Expiry resolution functions
# ============================================================================

def resolve_expiry_fixed(
    available_expiries: list[str], target_expiry: str,
) -> tuple[str, list[str]]:
    """Return *target_expiry* if it's in the available set.

    The broker-provided expiry list is authoritative.  If the requested
    expiry is not listed, a blocking ``EXPIRY_UNAVAILABLE`` error is
    raised — the resolver does NOT silently clamp to the nearest expiry.
    """
    if not available_expiries:
        raise ValueError(
            "EXPIRY_UNAVAILABLE: No expiries are available for this symbol."
        )
    if target_expiry in available_expiries:
        return target_expiry, []
    raise ValueError(
        f"EXPIRY_UNAVAILABLE: Expiry {target_expiry} is not listed. "
        f"Available: {', '.join(sorted(available_expiries))}"
    )


def resolve_expiry_current_week(available_expiries: list[str], today: date | None = None) -> tuple[str, list[str]]:
    """Nearest listed expiry that is on or after today.

    The broker-provided expiry list is the sole source of truth.  This
    function does NOT assume any specific expiry weekday (Tuesday,
    Thursday, etc.) or compute calendar-week boundaries.  Holidays are
    naturally handled because the broker omits holiday dates from its
    listed expiries.
    """
    if not available_expiries:
        raise ValueError("No expiries are available.")

    today = today or date.today()

    # Expiries on or after today, sorted chronologically
    future = sorted(
        e for e in available_expiries
        if _parse_expiry(e) is not None and _parse_expiry(e) >= today
    )
    if future:
        return future[0], []

    # All listed expiries are in the past — fallback to nearest
    return _nearest_expiry_by_date(available_expiries, today)


def resolve_expiry_next_week(available_expiries: list[str], today: date | None = None) -> tuple[str, list[str]]:
    """Second-nearest listed expiry on or after today.

    The broker-provided expiry list is the sole source of truth.  The
    first listed expiry >= today is "current week"; this function returns
    the next one after that.
    """
    if not available_expiries:
        raise ValueError("No expiries are available.")

    today = today or date.today()

    # Expiries on or after today, sorted chronologically
    future = sorted(
        e for e in available_expiries
        if _parse_expiry(e) is not None and _parse_expiry(e) >= today
    )
    if len(future) >= 2:
        return future[1], []

    # Fewer than two future expiries — fallback to nearest
    return _nearest_expiry_by_date(available_expiries, today)


def resolve_expiry_monthly(available_expiries: list[str], today: date | None = None) -> tuple[str, list[str]]:
    """Latest listed expiry in the current calendar month."""
    if not available_expiries:
        raise ValueError("No expiries are available.")

    today = today or date.today()
    candidates = [
        e for e in available_expiries
        if _parse_expiry(e) is not None
        and _parse_expiry(e).year == today.year
        and _parse_expiry(e).month == today.month
    ]
    if not candidates:
        return _nearest_expiry_by_date(available_expiries, today)

    candidates.sort(reverse=True)  # latest first
    return candidates[0], []


def resolve_expiry_dte_range(
    available_expiries: list[str],
    dte_min: int,
    dte_max: int,
    today: date | None = None,
) -> tuple[str, list[str]]:
    """Expiry whose days-to-expiry falls in ``[dte_min, dte_max]``.

    When multiple expiries qualify, the one with the **highest DTE** (most
    time remaining) is selected.  This is a deterministic, simple heuristic
    that works well for 6.8A when no expiry-level liquidity data (OI,
    volume) is available.  Future phases may enhance selection with
    liquidity-weighted ranking.
    """
    if not available_expiries:
        raise ValueError("No expiries are available.")
    if dte_min is None or dte_max is None:
        raise ValueError("DTE range requires both min and max values.")

    today = today or date.today()
    candidates: list[tuple[str, int]] = []
    for e in available_expiries:
        d = _parse_expiry(e)
        if d is None:
            continue
        dte = (d - today).days
        if dte_min <= dte <= dte_max:
            candidates.append((e, dte))

    if not candidates:
        return _nearest_expiry_by_date(available_expiries, today)

    # Pick the one with the most time remaining
    candidates.sort(key=lambda t: t[1], reverse=True)
    return candidates[0][0], []


# ============================================================================
# Main resolver entry point
# ============================================================================

def resolve_leg(
    formula: LegFormula,
    chain_response: dict,
    available_expiries: list[str] | None = None,
    today: date | None = None,
) -> ResolverResult:
    """Resolve one leg formula against live chain data.

    Parameters
    ----------
    formula : LegFormula
        The leg specification (fixed or dynamic).
    chain_response : dict
        Canonical chain response from ``transform_chain``.
    available_expiries : list[str] | None
        Full list of listed expiry dates.  Required for non-fixed expiry
        modes.  When ``None`` only ``"fixed"`` expiry mode is supported.
    today : date | None
        Override for today's date (testing only).  Defaults to
        ``date.today()``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    rows = chain_rows(chain_response)
    strikes = sorted_strikes(rows)
    spot = spot_price(chain_response)

    # --- Strike resolution ---
    try:
        resolved_strike, strike_warnings, anchor, delta_actual = _resolve_strike(
            formula, rows, strikes, spot,
        )
        warnings.extend(strike_warnings)
    except ValueError as exc:
        errors.append(str(exc))
        return ResolverResult(errors=errors)

    # --- Expiry resolution ---
    if available_expiries is None:
        available_expiries = []

    try:
        resolved_expiry, expiry_warnings = _resolve_expiry(
            formula, available_expiries, today,
        )
        warnings.extend(expiry_warnings)
    except ValueError as exc:
        errors.append(str(exc))
        return ResolverResult(errors=errors)

    return ResolverResult(
        leg=ResolvedLeg(
            resolved_strike=resolved_strike,
            resolved_expiry=resolved_expiry,
            action=formula.action,
            option_type=formula.option_type,
            quantity=formula.quantity,
            lot_size=formula.lot_size,
            strike_mode_used=formula.strike_mode.value,
            expiry_mode_used=formula.expiry_mode.value,
            anchor_value=anchor,
            delta_actual=delta_actual,
            warnings=warnings,
        ),
        errors=errors,
    )


# ============================================================================
# Internal helpers
# ============================================================================

def _resolve_strike(
    formula: LegFormula,
    rows: list[dict],
    strikes: list[float],
    spot: float | None,
) -> tuple[float, list[str], float | None, float | None]:
    """Dispatch to the correct strike resolver.

    Returns ``(strike, warnings, anchor_value, delta_actual)``.
    """
    mode = formula.strike_mode

    if mode == StrikeMode.FIXED:
        strike, w = resolve_fixed_strike(strikes, formula.strike)
        return strike, w, None, None

    if mode == StrikeMode.ATM:
        strike = resolve_atm(strikes, spot)
        return strike, [], spot, None

    if mode == StrikeMode.ATM_OFFSET_STEPS:
        strike, w = resolve_atm_offset_steps(strikes, spot, formula.strike_offset_steps)
        return strike, w, spot, None

    if mode == StrikeMode.ATM_OFFSET:
        strike, w = resolve_atm_offset(strikes, spot, formula.strike_offset)
        return strike, w, spot, None

    if mode == StrikeMode.SPOT_OFFSET:
        strike, w = resolve_spot_offset(strikes, spot, formula.strike_offset)
        return strike, w, spot, None

    if mode == StrikeMode.DELTA:
        row, actual_delta, w = resolve_delta_target(
            rows, formula.option_type, formula.target_delta, spot,
        )
        return row["strike"], w, spot, actual_delta

    raise ValueError(f"Unknown strike mode: {mode}")


def _resolve_expiry(
    formula: LegFormula,
    available_expiries: list[str],
    today: date | None = None,
) -> tuple[str, list[str]]:
    """Dispatch to the correct expiry resolver.

    ``today`` is propagated to all expiry-mode functions so tests can
    control the date.  When ``None``, each function defaults to
    ``date.today()``.
    """
    mode = formula.expiry_mode

    if mode == ExpiryMode.FIXED:
        return resolve_expiry_fixed(available_expiries, formula.expiry)

    if mode == ExpiryMode.CURRENT_WEEK:
        return resolve_expiry_current_week(available_expiries, today)

    if mode == ExpiryMode.NEXT_WEEK:
        return resolve_expiry_next_week(available_expiries, today)

    if mode == ExpiryMode.MONTHLY:
        return resolve_expiry_monthly(available_expiries, today)

    if mode == ExpiryMode.DTE_RANGE:
        return resolve_expiry_dte_range(
            available_expiries, formula.expiry_dte_min, formula.expiry_dte_max, today,
        )

    raise ValueError(f"Unknown expiry mode: {mode}")


def _parse_expiry(expiry_str: str) -> date | None:
    """Parse a YYYY-MM-DD expiry string to a date, or None on failure."""
    try:
        return date.fromisoformat(expiry_str)
    except (ValueError, TypeError):
        return None


def _nearest_expiry_by_date(
    available_expiries: list[str], target: date,
) -> tuple[str, list[str]]:
    """Fallback: pick the listed expiry closest to *target*."""
    warnings: list[str] = []
    if not available_expiries:
        raise ValueError("No expiries available.")
    best = min(
        available_expiries,
        key=lambda e: abs((_parse_expiry(e) or date.max) - target),
    )
    warnings.append(f"No ideal expiry found; using nearest available {best}.")
    return best, warnings
