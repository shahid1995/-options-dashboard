"""Phase 6.5.0.3 — Execution Intent + Execution Router Foundation.

Establishes the broker-neutral execution boundary between EXIT INTENT /
STRATEGY RESOLUTION and PAPER / FUTURE LIVE EXECUTION:

    ExitSelector
        ↓
    Exit Target Resolution (frontend resolveExitTargets)
        ↓
    ExecutionIntent        ← this module (backend domain)
        ↓
    ExecutionRouter        ← this module (backend router)
        ├── PAPER → existing Paper Execution Engine
        └── LIVE  → explicitly disabled (LIVE_EXECUTION_DISABLED)

CRITICAL RULES:
- ExecutionIntent is broker-neutral: NO Upstox fields, NO instrument_key,
  NO transaction_type, NO access tokens.
- Position remains authoritative for NET portfolio exposure.
- StrategyLegExposure remains authoritative for per-execution/per-leg
  remaining attribution.
- BUY exposure → SELL execution; SELL exposure → BUY execution.
- ExecutionRouter does NOT duplicate paper execution logic.
- ExecutionRouter does NOT directly import UpstoxAdapter or app.services.upstox.
- LIVE execution is explicitly disabled.
- The existing market gate, cash/P&L, journal, idempotency, and
  StrategyLegExposure maintenance are NEVER bypassed.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.brokers.domain.enums import Side as BrokerSide


# ---------------------------------------------------------------------------
# Execution mode
# ---------------------------------------------------------------------------

class ExecutionMode(str, Enum):
    """Distinguishes HOW a target is executed. PAPER routes to the existing
    paper engine; LIVE will route to the broker gateway (future phase)."""
    PAPER = "PAPER"
    LIVE = "LIVE"


class ExecutionSource(str, Enum):
    """WHY this execution was requested. Preserves audit trail without
    creating new persistence."""
    EXIT_SELECTOR = "EXIT_SELECTOR"
    MANUAL_EXIT = "MANUAL_EXIT"
    BULK_EXIT = "BULK_EXIT"
    FUTURE_AUTOMATION = "FUTURE_AUTOMATION"


class ExecutionStatus(str, Enum):
    """Lifecycle of an ExecutionIntent after routing."""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    DISABLED = "DISABLED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Execution error taxonomy (§32)
# ---------------------------------------------------------------------------

class ExecutionErrorCode(str, Enum):
    """Application-level execution routing errors. Distinct from BrokerError
    (which belongs below the execution router at the broker adapter level)."""
    INVALID_EXECUTION_INTENT = "INVALID_EXECUTION_INTENT"
    EXECUTION_TARGET_NOT_FOUND = "EXECUTION_TARGET_NOT_FOUND"
    EXECUTION_TARGET_STALE = "EXECUTION_TARGET_STALE"
    EXECUTION_QUANTITY_INVALID = "EXECUTION_QUANTITY_INVALID"
    EXECUTION_QUANTITY_EXCEEDS_REMAINING = "EXECUTION_QUANTITY_EXCEEDS_REMAINING"
    EXECUTION_IDEMPOTENCY_CONFLICT = "EXECUTION_IDEMPOTENCY_CONFLICT"
    LIVE_EXECUTION_DISABLED = "LIVE_EXECUTION_DISABLED"
    PAPER_EXECUTION_FAILED = "PAPER_EXECUTION_FAILED"
    UNKNOWN_EXECUTION_MODE = "UNKNOWN_EXECUTION_MODE"


class ExecutionError(Exception):
    """A structured execution-routing failure."""

    def __init__(self, code: ExecutionErrorCode, message: str):
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# ExecutionTarget (§6)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionTarget:
    """Canonical, broker-neutral execution target.

    Contains enough information to execute the already-resolved exit without
    re-deriving intent. Carries BOTH the source exposure identity AND the
    inverse transaction required to close it.

    Key fields:
    - position_id: netted position identity (authoritative portfolio exposure)
    - strategy_leg_exposure_id: per-execution per-leg attribution identity
      (authoritative for targeting; None when unavailable)
    - strategy_execution_id: which strategy execution owns this exposure
    - symbol/expiry/strike/option_type: canonical instrument identity
      (NO broker-specific instrument_key)
    - source_action: the original strategy-leg action (BUY or SELL)
    - exit_side: the INVERSE transaction side (BUY→SELL, SELL→BUY)
    - quantity: requested lots to exit (must be ≤ remaining_quantity)
    - remaining_quantity: current remaining lots from the exposure
    - lot_size: contracts per lot (for cash/quantity calculations)
    """
    position_id: int
    source_action: str                       # "buy" | "sell" — the strategy-leg action
    exit_side: str                           # "buy" | "sell" — the inverse transaction
    quantity: int                            # lots to exit
    remaining_quantity: int                  # current remaining lots
    symbol: str
    expiry: str
    strike: float
    option_type: str                         # "call" | "put"
    lot_size: int
    strategy_leg_exposure_id: int | None = None
    strategy_execution_id: str | None = None
    price_override: float | None = None      # optional pre-resolved fill price

    def __post_init__(self):
        # Validate invariant: exit_side must be the inverse of source_action
        if self.source_action not in ("buy", "sell"):
            raise ExecutionError(
                ExecutionErrorCode.INVALID_EXECUTION_INTENT,
                f"source_action must be 'buy' or 'sell', got '{self.source_action}'",
            )
        expected_exit = "sell" if self.source_action == "buy" else "buy"
        if self.exit_side != expected_exit:
            raise ExecutionError(
                ExecutionErrorCode.INVALID_EXECUTION_INTENT,
                f"exit_side must be '{expected_exit}' for source_action='{self.source_action}', "
                f"got '{self.exit_side}'",
            )
        if self.quantity <= 0:
            raise ExecutionError(
                ExecutionErrorCode.EXECUTION_QUANTITY_INVALID,
                f"quantity must be positive, got {self.quantity}",
            )
        if self.remaining_quantity < 0:
            raise ExecutionError(
                ExecutionErrorCode.EXECUTION_QUANTITY_INVALID,
                f"remaining_quantity must be non-negative, got {self.remaining_quantity}",
            )


# ---------------------------------------------------------------------------
# ExecutionIntent (§5)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionIntent:
    """Broker-neutral execution intent.

    Represents WHAT the system has been instructed to execute. It does NOT
    represent HOW a broker executes it. Created after target resolution has
    succeeded (exit selector → resolved targets → execution intent).

    Not persisted to a database table: the existing PaperOrder /
    StrategyExecution / BulkExitRecord records provide the authoritative
    persistence for paper execution. This is a domain/application object.
    """
    intent_id: str
    user_id: str
    execution_mode: ExecutionMode
    source: ExecutionSource
    targets: list[ExecutionTarget]
    idempotency_key: str
    created_at: str
    strategy_execution_id: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    status: ExecutionStatus = ExecutionStatus.PENDING

    def __post_init__(self):
        if not self.user_id:
            raise ExecutionError(
                ExecutionErrorCode.INVALID_EXECUTION_INTENT,
                "user_id is required.",
            )
        if not self.targets:
            raise ExecutionError(
                ExecutionErrorCode.INVALID_EXECUTION_INTENT,
                "At least one ExecutionTarget is required.",
            )
        if not self.idempotency_key:
            raise ExecutionError(
                ExecutionErrorCode.INVALID_EXECUTION_INTENT,
                "idempotency_key is required.",
            )


def create_execution_intent(
    user_id: str,
    execution_mode: ExecutionMode,
    source: ExecutionSource,
    targets: list[ExecutionTarget],
    idempotency_key: str | None = None,
    strategy_execution_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionIntent:
    """Factory for ExecutionIntent with deterministic ID generation.

    ``idempotency_key`` defaults to a random hex token; callers that need
    idempotent replay must supply a deterministic key.
    """
    now = datetime.now(timezone.utc).isoformat()
    return ExecutionIntent(
        intent_id=secrets.token_hex(16),
        user_id=user_id,
        execution_mode=execution_mode,
        source=source,
        targets=list(targets),
        idempotency_key=idempotency_key or secrets.token_hex(16),
        created_at=now,
        strategy_execution_id=strategy_execution_id,
        reason=reason,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# ExecutionResult (§30)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Canonical result of executing an ExecutionIntent."""
    intent_id: str
    status: ExecutionStatus
    mode: ExecutionMode
    targets_attempted: int = 0
    targets_succeeded: int = 0
    targets_failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duplicated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exit Intent → Execution Intent conversion (§7)
# ---------------------------------------------------------------------------

def exit_intent_target_to_execution_target(
    position_id: int,
    strategy_execution_id: str | None,
    option_type: str,
    source_side: str,
    quantity: int,
    remaining_quantity: int,
    symbol: str,
    expiry: str,
    strike: float,
    lot_size: int,
    strategy_leg_exposure_id: int | None = None,
    price_override: float | None = None,
) -> ExecutionTarget:
    """Convert one resolved exit-intent target into a canonical
    ExecutionTarget.

    The key transformation is the SIDE INVERSION:
    - source_side (the strategy-leg action): "buy" | "sell"
    - exit_side (the inverse transaction): "sell" | "buy"

    ``strategy_leg_exposure_id`` is the authoritative per-execution/per-leg
    attribution identity when available. ``position_id`` is the netted
    position identity (authoritative for portfolio exposure).
    """
    normalized_source = source_side.strip().lower()
    if normalized_source not in ("buy", "sell"):
        raise ExecutionError(
            ExecutionErrorCode.INVALID_EXECUTION_INTENT,
            f"source_side must be 'buy' or 'sell', got '{source_side}'",
        )
    exit_side = "sell" if normalized_source == "buy" else "buy"
    normalized_ot = option_type.strip().lower()

    return ExecutionTarget(
        position_id=position_id,
        source_action=normalized_source,
        exit_side=exit_side,
        quantity=quantity,
        remaining_quantity=remaining_quantity,
        symbol=symbol.upper(),
        expiry=expiry,
        strike=strike,
        option_type=normalized_ot,
        lot_size=lot_size,
        strategy_leg_exposure_id=strategy_leg_exposure_id,
        strategy_execution_id=strategy_execution_id,
        price_override=price_override,
    )


def build_execution_targets_from_exposures(
    exposures: list[Any],
    quantity_mode: str = "ALL",
    requested_quantity: int | None = None,
) -> list[ExecutionTarget]:
    """Build ExecutionTargets from StrategyLegExposure ORM objects.

    ``exposures`` are StrategyLegExposure rows (authoritative per-execution
    per-leg attribution). Each open exposure with remaining_quantity > 0
    becomes one ExecutionTarget with the side inverted.

    Returns targets in deterministic order (exposure id ascending).
    """
    targets: list[ExecutionTarget] = []
    for exp in sorted(exposures, key=lambda e: e.id):
        if exp.status != "open" or exp.remaining_quantity <= 0:
            continue
        qty = exp.remaining_quantity if quantity_mode == "ALL" else (requested_quantity or 0)
        if qty <= 0:
            continue
        targets.append(ExecutionTarget(
            position_id=exp.position_id,
            source_action=exp.action,  # "buy" | "sell"
            exit_side="sell" if exp.action == "buy" else "buy",
            quantity=qty,
            remaining_quantity=exp.remaining_quantity,
            symbol=exp.symbol,
            expiry=exp.expiry,
            strike=exp.strike,
            option_type=exp.option_type,
            lot_size=0,  # callers should set lot_size from position
            strategy_leg_exposure_id=exp.id,
            strategy_execution_id=exp.execution_id,
        ))
    return targets


# ---------------------------------------------------------------------------
# Stale-target validation (§33)
# ---------------------------------------------------------------------------

def validate_targets_still_valid(
    targets: list[ExecutionTarget],
    db: Session,
    user_id: str,
) -> list[str]:
    """Revalidate execution targets against current database state.

    Checks each target before execution:
    - position exists and belongs to user
    - position is still open with sufficient quantity
    - StrategyLegExposure (if referenced) still supports the attribution

    Returns a list of error messages for invalid targets. Empty = all valid.
    """
    from app.models import Position, StrategyLegExposure

    errors: list[str] = []
    for i, target in enumerate(targets):
        position = db.get(Position, target.position_id)
        if position is None or position.user_id != user_id:
            errors.append(
                f"Target {i}: position {target.position_id} not found or not owned by user."
            )
            continue
        if position.status != "open" or position.net_quantity == 0:
            errors.append(
                f"Target {i}: position {target.position_id} is closed (net_quantity={position.net_quantity})."
            )
            continue
        if target.quantity > abs(position.net_quantity):
            errors.append(
                f"Target {i}: requested {target.quantity} lot(s) but position "
                f"{target.position_id} has only {abs(position.net_quantity)} lot(s)."
            )
            continue
        # Validate StrategyLegExposure when referenced
        if target.strategy_leg_exposure_id is not None:
            exposure = db.get(StrategyLegExposure, target.strategy_leg_exposure_id)
            if exposure is None or exposure.user_id != user_id:
                errors.append(
                    f"Target {i}: exposure {target.strategy_leg_exposure_id} not found "
                    f"or not owned by user."
                )
                continue
            if exposure.status != "open" or exposure.remaining_quantity <= 0:
                errors.append(
                    f"Target {i}: exposure {target.strategy_leg_exposure_id} is closed "
                    f"(remaining={exposure.remaining_quantity})."
                )
                continue
            if target.quantity > exposure.remaining_quantity:
                errors.append(
                    f"Target {i}: requested {target.quantity} lot(s) but exposure "
                    f"{target.strategy_leg_exposure_id} has only {exposure.remaining_quantity} "
                    f"lot(s) remaining."
                )
    return errors


# ---------------------------------------------------------------------------
# ExecutionRouter (§10)
# ---------------------------------------------------------------------------

class ExecutionRouter:
    """Routes ExecutionIntents to the appropriate execution backend.

    Currently supports:
    - PAPER: delegates to the existing Paper Execution Engine
    - LIVE: explicitly disabled (returns LIVE_EXECUTION_DISABLED)

    The router does NOT duplicate paper execution logic (position netting,
    average price, P&L, cash flow, journal, idempotency). It validates the
    intent and targets, then delegates to the existing trusted services.

    Does NOT directly import UpstoxAdapter or app.services.upstox.
    """

    def __init__(self, db: Session, price_resolver=None):
        """
        ``db``: SQLAlchemy session (for stale-target validation).
        ``price_resolver``: optional async callable
            ``(access_token, targets) -> {(symbol, expiry, strike, option_type): price}``.
            For PAPER mode this resolves authoritative market prices.
            When None, targets must carry price_override values.
        """
        self._db = db
        self._price_resolver = price_resolver

    async def execute_intent(
        self,
        intent: ExecutionIntent,
        access_token: str | None = None,
    ) -> ExecutionResult:
        """Route and execute an ExecutionIntent.

        1. Validate intent structure
        2. Validate targets against current state (stale protection)
        3. Route by execution_mode:
           - PAPER → _execute_paper(intent, access_token)
           - LIVE → _execute_live_disabled()
           - unknown → error
        """
        result = ExecutionResult(
            intent_id=intent.intent_id,
            status=ExecutionStatus.PENDING,
            mode=intent.execution_mode,
            targets_attempted=len(intent.targets),
        )

        # Route by mode
        if intent.execution_mode == ExecutionMode.PAPER:
            # PAPER: first attempt the execution (which includes idempotent
            # replay check BEFORE stale validation, matching the existing
            # paper engine's pattern: find_exit_replay runs before
            # open-position validation). If execution fails due to stale
            # state, the stale errors are surfaced.
            return await self._execute_paper(intent, result, access_token)
        elif intent.execution_mode == ExecutionMode.LIVE:
            return self._execute_live_disabled(intent, result)
        else:
            result.status = ExecutionStatus.FAILED
            result.errors = [f"Unknown execution mode: {intent.execution_mode}"]
            intent.status = ExecutionStatus.FAILED
            return result

    async def _execute_paper(
        self,
        intent: ExecutionIntent,
        result: ExecutionResult,
        access_token: str | None,
    ) -> ExecutionResult:
        """Execute targets through the existing paper engine.

        Each target is translated to the existing exit_position contract:
        - position_id
        - quantity (lots)
        - fill_price (resolved from market data or price_override)
        - client_order_id (idempotent per target)

        The existing paper engine handles:
        - position validation
        - quantity validation
        - fill price resolution (when not overridden)
        - position mutation
        - StrategyLegExposure maintenance
        - journal attribution
        - cash/P&L
        - idempotency
        """
        from app.services.paper_execution import (
            ExitRequestIn,
            PaperExecutionError,
            exit_position,
            find_exit_replay,
        )

        succeeded = 0
        failed = 0
        errors: list[str] = []

        for i, target in enumerate(intent.targets):
            client_order_id = f"{intent.idempotency_key}:t{i}"
            exit_request = ExitRequestIn(
                client_order_id=client_order_id,
                quantity=target.quantity,
                exit_price=target.price_override,
            )
            try:
                # Check idempotent replay first (before validation)
                from app.models import Position as PositionModel
                position = self._db.get(PositionModel, target.position_id)
                if position is None or position.user_id != intent.user_id:
                    raise PaperExecutionError(
                        "POSITION_NOT_FOUND",
                        f"Position {target.position_id} not found.",
                    )
                replay = find_exit_replay(
                    intent.user_id, position, client_order_id, self._db
                )
                if replay is not None:
                    result.results.append({
                        "target_index": i,
                        "position_id": target.position_id,
                        "duplicated": True,
                        "order": replay.order.model_dump(mode="json") if hasattr(replay, 'order') else {},
                    })
                    succeeded += 1
                    result.duplicated = True
                    continue

                # Validate position is still open
                if position.status != "open" or position.net_quantity == 0:
                    raise PaperExecutionError(
                        "INSUFFICIENT_POSITION",
                        f"Position {target.position_id} is closed.",
                    )
                if target.quantity > abs(position.net_quantity):
                    raise PaperExecutionError(
                        "INSUFFICIENT_POSITION",
                        f"Only {abs(position.net_quantity)} lot(s) available.",
                    )

                # Price: use target's override or require the caller to have
                # pre-resolved market prices and set them on the target.
                fill_price = target.price_override
                if fill_price is None:
                    raise PaperExecutionError(
                        "CHAIN_DATA_MISSING",
                        "No fill price available. Price must be resolved before routing.",
                    )

                exit_result = exit_position(
                    intent.user_id,
                    target.position_id,
                    exit_request,
                    self._db,
                    fill_price,
                    commit=True,
                    exit_side=target.exit_side,
                    target_exposure_id=target.strategy_leg_exposure_id,
                )
                result.results.append({
                    "target_index": i,
                    "position_id": target.position_id,
                    "duplicated": False,
                    "order": exit_result.order.model_dump(mode="json") if hasattr(exit_result, 'order') else {},
                    "position": exit_result.position.model_dump(mode="json") if hasattr(exit_result, 'position') else {},
                })
                succeeded += 1

            except PaperExecutionError as exc:
                failed += 1
                errors.append(f"Target {i} (position {target.position_id}): {exc.code}: {exc.message}")
            except ExecutionError as exc:
                failed += 1
                errors.append(f"Target {i} (position {target.position_id}): {exc.code.value}: {exc.message}")
            except Exception as exc:
                failed += 1
                errors.append(f"Target {i} (position {target.position_id}): unexpected error: {exc}")

        result.targets_succeeded = succeeded
        result.targets_failed = failed
        result.errors = errors

        if succeeded == 0 and failed > 0:
            result.status = ExecutionStatus.FAILED
        elif failed > 0:
            result.status = ExecutionStatus.PARTIAL
        else:
            result.status = ExecutionStatus.SUCCESS

        intent.status = result.status
        return result

    def _execute_live_disabled(
        self,
        intent: ExecutionIntent,
        result: ExecutionResult,
    ) -> ExecutionResult:
        """LIVE execution is explicitly disabled (§10, §19).

        Returns a deterministic DISABLED result. Does NOT call BrokerGateway.
        Does NOT import UpstoxAdapter.
        """
        result.status = ExecutionStatus.DISABLED
        result.targets_succeeded = 0
        result.targets_failed = result.targets_attempted
        result.errors = [
            "Live execution is disabled. "
            "Use PAPER mode or wait for the live execution phase."
        ]
        intent.status = ExecutionStatus.DISABLED
        return result


# ---------------------------------------------------------------------------
# Execution-side translation helpers (§29)
# ---------------------------------------------------------------------------

def exit_side_for(source_action: str) -> str:
    """Invert a strategy-leg action to get the exit transaction side.

    BUY exposure → SELL to exit.
    SELL exposure → BUY to exit.
    """
    normalized = source_action.strip().lower()
    if normalized == "buy":
        return "sell"
    if normalized == "sell":
        return "buy"
    raise ExecutionError(
        ExecutionErrorCode.INVALID_EXECUTION_INTENT,
        f"source_action must be 'buy' or 'sell', got '{source_action}'",
    )


def source_action_for_exit(exit_side: str) -> str:
    """Given an exit transaction side, what was the original exposure action?

    SELL exit ← BUY exposure.
    BUY exit ← SELL exposure.
    """
    normalized = exit_side.strip().lower()
    if normalized == "sell":
        return "buy"
    if normalized == "buy":
        return "sell"
    raise ExecutionError(
        ExecutionErrorCode.INVALID_EXECUTION_INTENT,
        f"exit_side must be 'buy' or 'sell', got '{exit_side}'",
    )
