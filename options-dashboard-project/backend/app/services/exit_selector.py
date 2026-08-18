"""Phase 6.5.0.4 — Server-Side Exit Intent Resolution.

Turns the frontend Exit Selector architecture into a SERVER-AUTHORITATIVE,
LEG-AWARE exit flow. The frontend selector is NOT authoritative — the server
independently resolves the requested selector against the authenticated
user's current StrategyLegExposure and Position data.

Target architecture:

    User selector (scope + option_type + action + quantity_mode)
        ↓
    resolve_server_exit_targets()   ← this module
        ↓
    ExecutionTarget[]               ← from Phase 6.5.0.3
        ↓
    ExecutionIntent                 ← from Phase 6.5.0.3
        ↓
    ExecutionRouter                 ← from Phase 6.5.0.3
        ↓
    Existing Paper Execution Engine

CRITICAL RULES:
- The frontend selector is a REQUEST, not an authority.
- The server resolves attribution from StrategyLegExposure (authoritative
  per-execution/per-leg remaining).
- Position is authoritative for NET portfolio exposure.
- User identity comes from authentication, never from the request body.
- CE → CALL, PE → PUT normalization.
- BUY/SELL represent the ORIGINAL strategy-leg action.
- BUY exposure → SELL execution (side inversion happens in ExecutionTarget).
- Original quantity is NEVER used; only current remaining_quantity.
- Stale targets are rejected safely.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Position, StrategyExecution, StrategyLegExposure
from app.services.execution_intent import (
    ExecutionError,
    ExecutionErrorCode,
    ExecutionTarget,
    exit_side_for,
)


# ---------------------------------------------------------------------------
# Selector normalization (§5)
# ---------------------------------------------------------------------------

def normalize_option_type(value: str | None) -> str | None:
    """Normalize option type: CE→CALL, PE→PUT, call/put pass through.

    Returns lowercase canonical: "call" | "put" | None.
    """
    if value is None:
        return None
    v = str(value).strip().upper()
    if v in ("CALL", "CE", "C"):
        return "call"
    if v in ("PUT", "PE", "P"):
        return "put"
    return None


def normalize_action(value: str | None) -> str | None:
    """Normalize side/action: buy/sell pass through.

    Returns lowercase: "buy" | "sell" | None.
    """
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in ("buy", "b"):
        return "buy"
    if v in ("sell", "s"):
        return "sell"
    return None


def normalize_scope(value: str | None) -> str | None:
    """Normalize scope: POSITION | STRATEGY | PORTFOLIO."""
    if value is None:
        return None
    v = str(value).strip().upper()
    if v in ("POSITION", "STRATEGY", "PORTFOLIO"):
        return v
    return None


def normalize_quantity_mode(value: str | None) -> str | None:
    """Normalize quantity mode: ALL | QUANTITY."""
    if value is None:
        return None
    v = str(value).strip().upper()
    if v in ("ALL", "QUANTITY"):
        return v
    return None


# ---------------------------------------------------------------------------
# Server-side exit selector resolver (§7)
# ---------------------------------------------------------------------------

class ExitSelectorError(Exception):
    """A structured exit-selector resolution failure."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def resolve_server_exit_targets(
    db: Session,
    user_id: str,
    scope: str,
    strategy_execution_id: str | None = None,
    position_id: int | None = None,
    exposure_id: int | None = None,
    option_type: str | None = None,
    action: str | None = None,
    quantity_mode: str = "ALL",
    quantity: int | None = None,
) -> list[ExecutionTarget]:
    """Server-authoritative exit target resolution.

    Queries current database state (StrategyLegExposure + Position) and
    resolves the user's selector into a list of ExecutionTargets.

    Args:
        db: SQLAlchemy session (read-only queries).
        user_id: Authenticated user ID (NEVER from request body).
        scope: "POSITION" | "STRATEGY" | "PORTFOLIO".
        strategy_execution_id: Required for STRATEGY scope.
        position_id: Required for POSITION scope.
        exposure_id: Optional — target a specific StrategyLegExposure.
        option_type: Optional filter — "CALL" | "PUT" (normalized).
        action: Optional filter — "BUY" | "SELL" (the source exposure action).
        quantity_mode: "ALL" | "QUANTITY".
        quantity: Required when quantity_mode == "QUANTITY".

    Returns:
        Deterministically ordered list of ExecutionTarget.

    Raises:
        ExitSelectorError for any validation failure.
    """
    # --- Validate inputs ---
    scope = normalize_scope(scope)
    if scope is None:
        raise ExitSelectorError("INVALID_INTENT", "Invalid or missing scope.")

    option_type_norm = normalize_option_type(option_type)
    action_norm = normalize_action(action)

    quantity_mode = normalize_quantity_mode(quantity_mode)
    if quantity_mode is None:
        raise ExitSelectorError("INVALID_INTENT", "Invalid or missing quantity_mode.")

    if quantity_mode == "QUANTITY":
        if quantity is None:
            raise ExitSelectorError("MISSING_QUANTITY", "QUANTITY mode requires a quantity.")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ExitSelectorError("INVALID_QUANTITY", "Exit quantity must be a positive whole number of lots.")

    if scope == "POSITION" and position_id is None:
        raise ExitSelectorError("INVALID_INTENT", "POSITION scope requires position_id.")

    if scope == "STRATEGY" and not strategy_execution_id:
        raise ExitSelectorError("INVALID_INTENT", "STRATEGY scope requires strategy_execution_id.")

    # --- Build base query: open exposures owned by the user ---
    base_filters = [
        StrategyLegExposure.user_id == user_id,
        StrategyLegExposure.status == "open",
        StrategyLegExposure.remaining_quantity > 0,
    ]

    # Scope filters
    if scope == "POSITION":
        # Verify position exists, belongs to user, and is open
        position = db.get(Position, position_id)
        if position is None or position.user_id != user_id:
            raise ExitSelectorError("TARGET_NOT_FOUND", "Position not found or not owned by user.")
        if position.status != "open" or position.net_quantity == 0:
            raise ExitSelectorError("TARGET_NOT_FOUND", "Position is closed.")
        base_filters.append(StrategyLegExposure.position_id == position_id)

    elif scope == "STRATEGY":
        # Verify strategy execution exists and belongs to user
        execution = db.scalar(
            select(StrategyExecution).where(
                StrategyExecution.user_id == user_id,
                StrategyExecution.execution_id == strategy_execution_id,
            )
        )
        if execution is None:
            raise ExitSelectorError("TARGET_NOT_FOUND", "Strategy execution not found.")
        base_filters.append(StrategyLegExposure.execution_id == strategy_execution_id)

    # PORTFOLIO: no additional scope filter — all user's open exposures

    # Individual exposure targeting
    if exposure_id is not None:
        base_filters.append(StrategyLegExposure.id == exposure_id)

    # Selector filters
    if option_type_norm is not None:
        base_filters.append(StrategyLegExposure.option_type == option_type_norm)
    if action_norm is not None:
        base_filters.append(StrategyLegExposure.action == action_norm)

    # --- Query exposures ---
    exposures = list(
        db.scalars(
            select(StrategyLegExposure)
            .where(*base_filters)
            .order_by(StrategyLegExposure.id.asc())
        ).all()
    )

    if not exposures:
        raise ExitSelectorError(
            "NO_MATCHING_TARGETS",
            "No open exposure matches the exit selector.",
        )

    # --- Validate each exposure's linked position ---
    # (ensure position exists, belongs to user, and is open)
    position_cache: dict[int, Position] = {}
    valid_exposures: list[StrategyLegExposure] = []
    for exp in exposures:
        if exp.position_id not in position_cache:
            pos = db.get(Position, exp.position_id)
            position_cache[exp.position_id] = pos
        pos = position_cache[exp.position_id]
        if pos is None or pos.user_id != user_id:
            continue  # skip orphaned exposures (safety)
        if pos.status != "open" or pos.net_quantity == 0:
            continue  # skip exposures for closed positions
        valid_exposures.append(exp)

    if not valid_exposures:
        raise ExitSelectorError(
            "NO_MATCHING_TARGETS",
            "No open exposure matches the exit selector.",
        )

    # --- Quantity resolution ---
    if quantity_mode == "QUANTITY":
        if len(valid_exposures) > 1:
            raise ExitSelectorError(
                "AMBIGUOUS_EXIT_QUANTITY",
                f"QUANTITY mode matched {len(valid_exposures)} exposures — "
                "specify an unambiguous selector or exposure_id.",
            )
        exp = valid_exposures[0]
        if quantity > exp.remaining_quantity:
            raise ExitSelectorError(
                "EXIT_QUANTITY_EXCEEDS_REMAINING",
                f"Requested {quantity} lot(s) but only {exp.remaining_quantity} remain.",
            )

    # --- Build ExecutionTargets ---
    targets: list[ExecutionTarget] = []
    for exp in valid_exposures:
        qty = exp.remaining_quantity if quantity_mode == "ALL" else quantity

        # Get lot_size from the linked position
        pos = position_cache.get(exp.position_id)
        lot_size = pos.lot_size if pos else 0

        target = ExecutionTarget(
            position_id=exp.position_id,
            source_action=exp.action,  # "buy" | "sell" — the strategy-leg action
            exit_side=exit_side_for(exp.action),  # "sell" | "buy" — the inverse
            quantity=qty,
            remaining_quantity=exp.remaining_quantity,
            symbol=exp.symbol,
            expiry=exp.expiry,
            strike=exp.strike,
            option_type=exp.option_type,
            lot_size=lot_size,
            strategy_leg_exposure_id=exp.id,
            strategy_execution_id=exp.execution_id,
        )
        targets.append(target)

    # --- Deterministic ordering: [option_type, source_action, exposure_id] ---
    targets.sort(key=lambda t: (t.option_type, t.source_action, t.strategy_leg_exposure_id or 0))

    return targets
