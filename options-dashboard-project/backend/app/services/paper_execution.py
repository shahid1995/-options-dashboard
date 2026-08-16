"""Server-authoritative paper trading engine (Phase 5.0).

The backend is the single source of truth for paper orders, fills,
positions, cash and P&L. This service implements:

- the order status lifecycle + pure transition validator
- netted positions (weighted-average entry, realized P&L on reduction,
  partial/full exits, reversal)
- the auditable cash ledger (``PaperTransaction``): available cash is
  derived as ``starting_capital + SUM(amount)``
- idempotent strategy executions (``client_order_id`` unique per user) and
  idempotent exits
- strategy grouping (all legs of one execution share ``execution_id``)
- portfolio summary, strategy-grouped view and a reconciliation check

Execution is ATOMIC: every validation (market gate, chain data, prices)
happens BEFORE any row is written, so a successful execution is FILLED with
all orders filled and a failed one writes nothing. No fake async fills, no
partial-success ambiguity.

All quantities are LOTS. Rupee exposure scales by ``lot_size``
(contracts per lot). Position quantity convention: BUY = +, SELL = −.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Leg,
    PaperAccount,
    PaperOrder,
    PaperTransaction,
    Position,
    StrategyExecution,
    Trade,
)
from app.schemas import (
    ExecutionOut,
    ExitOut,
    OrderOut,
    PortfolioGroupOut,
    PortfolioOut,
    PositionOut,
    PortfolioSummaryOut,
    ReconcileOut,
)

DEFAULT_STARTING_CAPITAL = 500000

# ---- Order status lifecycle (§5) -------------------------------------------

ORDER_STATUSES = frozenset({"PENDING", "FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"})
ORDER_TRANSITIONS = {
    "PENDING": {"FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED"},
    "PARTIALLY_FILLED": {"FILLED", "CANCELLED", "REJECTED"},
    "FILLED": set(),
    "CANCELLED": set(),
    "REJECTED": set(),
}

EXECUTION_STATUSES = frozenset({"PENDING", "FILLED", "PARTIAL", "FAILED", "CANCELLED"})

# ---- Structured errors (§32) ------------------------------------------------


class PaperExecutionError(Exception):
    """A structured paper-execution failure.

    ``code`` is one of the documented error codes (MARKET_CLOSED,
    CHAIN_DATA_MISSING, INVALID_QUANTITY, POSITION_NOT_FOUND,
    INSUFFICIENT_POSITION, DUPLICATE_REQUEST, INVALID_STATE_TRANSITION,
    EXECUTION_FAILED). ``message`` is human-readable.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---- Pure helpers -----------------------------------------------------------


def can_transition(current: str, target: str) -> bool:
    """Whether ``current → target`` is a valid order-status transition."""
    return target in ORDER_TRANSITIONS.get(current, set())


def transition(current: str, target: str) -> str:
    """Validate and apply an order-status transition (pure)."""
    if not can_transition(current, target):
        raise PaperExecutionError(
            "INVALID_STATE_TRANSITION",
            f"Invalid order status transition: {current} → {target}",
        )
    return target


def cash_flow(action: str, price: float, quantity: int, lot_size: int) -> float:
    """Signed rupee cash flow for a fill: buy pays out (−), sell receives (+)."""
    direction = -1 if action == "buy" else 1
    return round(direction * price * quantity * lot_size, 2)


def _journal_dir(action: str) -> int:
    """Premium-flow direction matching the legacy journal: buy = +1, sell = −1."""
    return -1 if action == "sell" else 1


def apply_fill(
    net_quantity: int,
    average_price: float,
    action: str,
    quantity: int,
    price: float,
    lot_size: int,
) -> tuple[int, float, float]:
    """Apply one fill to a netted position.

    Returns ``(new_net_quantity, new_average_price, realized_pnl_rupees)``.

    - Same direction (or a fresh position): weighted-average entry price.
    - Opposite direction, partial/full: realized P&L against the existing
      average; the average is unchanged for the remaining quantity.
    - Opposite direction, overshooting (reversal): the covered part realizes,
      the leftover flips the position at the fill price.
    """
    signed = quantity if action == "buy" else -quantity
    new_net = net_quantity + signed

    if net_quantity == 0 or net_quantity * signed > 0:
        if new_net == 0:
            return (0, average_price, 0.0)
        new_avg = (abs(net_quantity) * average_price + quantity * price) / abs(new_net)
        return (new_net, new_avg, 0.0)

    covered = min(abs(signed), abs(net_quantity))
    if net_quantity > 0:  # long position reduced/closed by a sell
        realized = (price - average_price) * covered * lot_size
    else:  # short position reduced/closed by a buy
        realized = (average_price - price) * covered * lot_size

    if abs(signed) <= abs(net_quantity):
        return (new_net, average_price, realized)
    return (new_net, price, realized)


def unrealized_pnl(net_quantity: int, average_price: float, price: float, lot_size: int) -> float:
    """Unrealized P&L of a position marked at ``price`` (rupees).

    Long: (price − avg) × qty × lot. Short: (avg − price) × qty × lot.
    A zero/closed position has zero unrealized P&L.
    """
    if net_quantity == 0:
        return 0.0
    if net_quantity > 0:
        return round((price - average_price) * net_quantity * lot_size, 2)
    return round((average_price - price) * abs(net_quantity) * lot_size, 2)


# ---- DB helpers -------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_execution_id() -> str:
    return secrets.token_hex(16)


def _get_or_create_account(user_id: str, starting_capital: float | None, db: Session) -> PaperAccount:
    account = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
    if account is None:
        account = PaperAccount(
            user_id=user_id,
            starting_capital=starting_capital or DEFAULT_STARTING_CAPITAL,
        )
        db.add(account)
        db.flush()
    elif starting_capital is not None:
        account.starting_capital = starting_capital
        account.updated_at = _now()
    return account


def _get_position(
    db: Session,
    user_id: str,
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
) -> Position | None:
    return db.scalar(
        select(Position).where(
            Position.user_id == user_id,
            Position.symbol == symbol,
            Position.expiry == expiry,
            Position.strike == strike,
            Position.option_type == option_type,
        )
    )


def _instrument_orders(db: Session, user_id: str, position: Position) -> list[PaperOrder]:
    """All FILLED orders (entries + exits) for the position's instrument."""
    return list(
        db.scalars(
            select(PaperOrder)
            .where(
                PaperOrder.user_id == user_id,
                PaperOrder.symbol == position.symbol,
                PaperOrder.expiry == position.expiry,
                PaperOrder.strike == position.strike,
                PaperOrder.option_type == position.option_type,
                PaperOrder.status == "FILLED",
            )
            .order_by(PaperOrder.id.asc())
        ).all()
    )


def _transaction_type(kind: str, action: str) -> str:
    if kind == "entry":
        return "ENTRY_DEBIT" if action == "buy" else "ENTRY_CREDIT"
    return "EXIT_DEBIT" if action == "buy" else "EXIT_CREDIT"


def _serialize_order(order: PaperOrder) -> dict:
    return OrderOut.model_validate(order).model_dump(mode="json")


def _serialize_position(position: Position) -> dict:
    return PositionOut.model_validate(position).model_dump(mode="json")


# ---- Strategy execution (§7/§8) ---------------------------------------------


def execute_strategy(user_id: str, request, db: Session, prices: dict) -> ExecutionOut:
    """Create one strategy execution atomically.

    ``prices`` maps ``(expiry, strike, option_type) -> fill price`` and is
    resolved by the router from the authoritative chain data BEFORE any
    writes happen. Every leg must resolve; otherwise ``CHAIN_DATA_MISSING``
    is raised and nothing is written (never a misleading partial success).

    Idempotency: a retried ``client_order_id`` returns the ORIGINAL
    execution untouched — no second execution, no second orders, no
    double-counted cash, no duplicate journal record.
    """
    now = _now()
    symbol = request.symbol.upper()

    existing = db.scalar(
        select(StrategyExecution).where(
            StrategyExecution.user_id == user_id,
            StrategyExecution.client_order_id == request.client_order_id,
        )
    )
    if existing is not None:
        return _execution_out(existing, db, duplicated=True)

    # Pre-validate every leg resolves to a market price before writing.
    missing = []
    for leg in request.legs:
        key = (leg.expiration_date, leg.strike_price, leg.option_type)
        price = prices.get(key)
        if price is None or price <= 0:
            missing.append(
                f"Leg {leg.option_type.upper()} {leg.strike_price:g}: market data "
                f"unavailable for expiry {leg.expiration_date}."
            )
    if missing:
        raise PaperExecutionError(
            "CHAIN_DATA_MISSING",
            " ".join(missing) + " Paper order was not executed.",
        )

    execution_id = _new_execution_id()
    _get_or_create_account(user_id, request.starting_capital, db)

    execution = StrategyExecution(
        user_id=user_id,
        execution_id=execution_id,
        client_order_id=request.client_order_id,
        strategy_id=request.strategy_id,
        strategy_tag=request.strategy_tag or "Custom",
        symbol=symbol,
        status="FILLED",
        entry_net=0.0,
        entry_at=now,
    )
    db.add(execution)
    db.flush()

    # Legacy journal record (same execution id + idempotency key so the
    # journal UI stays consistent and retries can never duplicate it).
    trade = Trade(
        user_id=user_id,
        symbol=symbol,
        strategy_tag=request.strategy_tag or "Custom",
        status="open",
        entry_net=0.0,
        entry_at=now,
        strategy_execution_id=execution_id,
        client_order_id=request.client_order_id,
    )
    db.add(trade)
    db.flush()

    entry_net = 0.0
    orders: list[PaperOrder] = []
    for i, leg in enumerate(request.legs):
        fill_price = round(prices[(leg.expiration_date, leg.strike_price, leg.option_type)], 2)
        leg_symbol = leg.symbol.upper()

        order = PaperOrder(
            user_id=user_id,
            client_order_id=f"{request.client_order_id}:{i}",
            execution_id=execution_id,
            kind="entry",
            symbol=leg_symbol,
            expiry=leg.expiration_date,
            strike=leg.strike_price,
            option_type=leg.option_type,
            action=leg.action,
            quantity=leg.quantity,
            lot_size=leg.lot_size,
            status="FILLED",
            filled_quantity=leg.quantity,
            fill_price=fill_price,
            price_source="market",
        )
        db.add(order)
        db.flush()

        # Netted position (BUY = +, SELL = −). Same instrument nets into the
        # same row; the first opening execution stays the group identity.
        position = _get_position(db, user_id, leg_symbol, leg.expiration_date, leg.strike_price, leg.option_type)
        if position is None:
            position = Position(
                user_id=user_id,
                symbol=leg_symbol,
                expiry=leg.expiration_date,
                strike=leg.strike_price,
                option_type=leg.option_type,
                net_quantity=0,
                average_entry_price=0.0,
                lot_size=leg.lot_size,
                realized_pnl=0.0,
                status="open",
                strategy_execution_id=execution_id,
                opened_at=now,
            )
            db.add(position)
            db.flush()
        elif position.status == "closed":
            # Reopening a previously closed instrument: the same row resumes.
            # Lifetime realized P&L for the instrument is kept (never erased)
            # and the new entry starts a fresh net quantity at the new price.
            position.status = "open"
            position.closed_at = None
            position.updated_at = now

        new_net, new_avg, realized = apply_fill(
            position.net_quantity, position.average_entry_price,
            leg.action, leg.quantity, fill_price, leg.lot_size,
        )
        position.net_quantity = new_net
        position.average_entry_price = new_avg
        position.lot_size = leg.lot_size
        position.realized_pnl = round(position.realized_pnl + realized, 2)
        position.updated_at = now

        amount = cash_flow(leg.action, fill_price, leg.quantity, leg.lot_size)
        db.add(
            PaperTransaction(
                user_id=user_id,
                execution_id=execution_id,
                order_id=order.id,
                type=_transaction_type("entry", leg.action),
                amount=amount,
                created_at=now,
            )
        )
        entry_net += _journal_dir(leg.action) * fill_price * leg.quantity * leg.lot_size

        # Legacy journal leg mirroring the order (premium = authoritative fill).
        jleg = Leg(
            trade_id=trade.id,
            symbol=leg_symbol,
            expiration_date=leg.expiration_date,
            strike_price=leg.strike_price,
            option_type=leg.option_type,
            action=leg.action,
            premium=fill_price,
            quantity=leg.quantity,
            lot_size=leg.lot_size,
            entry_at=now,
        )
        db.add(jleg)
        db.flush()
        order.journal_leg_id = jleg.id
        order.position_id = position.id
        orders.append(order)

    execution.entry_net = round(entry_net, 2)
    trade.entry_net = round(entry_net, 2)
    db.commit()
    db.refresh(execution)
    return _execution_out(execution, db, duplicated=False)


# ---- Position exit (§28) -----------------------------------------------------


def find_exit_replay(user_id: str, position: Position, client_order_id: str, db: Session) -> ExitOut | None:
    """Idempotent replay lookup for a position exit.

    Must run BEFORE any open-position/price validation so a retried exit
    returns the ORIGINAL result even after the position has closed and even
    if market data is currently unavailable.
    """
    existing = db.scalar(
        select(PaperOrder).where(
            PaperOrder.user_id == user_id,
            PaperOrder.client_order_id == client_order_id,
            PaperOrder.kind == "exit",
            PaperOrder.position_id == position.id,
        )
    )
    if existing is None:
        return None
    return ExitOut(order=_serialize_order(existing), position=_serialize_position(position), duplicated=True)


def exit_position(user_id: str, position_id: int, request, db: Session, fill_price: float) -> ExitOut:
    """Exit (partially or fully) a paper position at the authoritative price.

    Validates: position exists + belongs to the user, quantity is valid and
    available, then applies the fill, records the exit order + ledger
    transaction, closes the journal legs FIFO and marks the position CLOSED
    when no residual quantity remains (the record is kept, never deleted).

    Idempotent: retrying the same ``client_order_id`` for the same position
    returns the original exit order + the current position.
    """
    now = _now()

    position = db.get(Position, position_id)
    if position is None or position.user_id != user_id:
        raise PaperExecutionError("POSITION_NOT_FOUND", "Position not found.")

    existing = find_exit_replay(user_id, position, request.client_order_id, db)
    if existing is not None:
        return existing

    if position.status != "open" or position.net_quantity == 0:
        raise PaperExecutionError(
            "INSUFFICIENT_POSITION",
            "Position is closed — no quantity available to exit.",
        )

    qty = request.quantity or abs(position.net_quantity)
    if qty <= 0:
        raise PaperExecutionError("INVALID_QUANTITY", "Exit quantity must be positive.")
    if qty > abs(position.net_quantity):
        raise PaperExecutionError(
            "INSUFFICIENT_POSITION",
            f"Only {abs(position.net_quantity)} lot(s) available to exit.",
        )

    action = "sell" if position.net_quantity > 0 else "buy"
    new_net, new_avg, realized = apply_fill(
        position.net_quantity, position.average_entry_price,
        action, qty, fill_price, position.lot_size,
    )

    order = PaperOrder(
        user_id=user_id,
        client_order_id=request.client_order_id,
        execution_id=None,
        position_id=position.id,
        kind="exit",
        symbol=position.symbol,
        expiry=position.expiry,
        strike=position.strike,
        option_type=position.option_type,
        action=action,
        quantity=qty,
        lot_size=position.lot_size,
        status="FILLED",
        filled_quantity=qty,
        fill_price=round(fill_price, 2),
        price_source="market",
        realized_pnl=round(realized, 2),
    )
    db.add(order)
    db.flush()

    position.net_quantity = new_net
    position.average_entry_price = new_avg
    position.realized_pnl = round(position.realized_pnl + realized, 2)
    position.updated_at = now
    was_open = True
    if new_net == 0:
        position.status = "closed"
        position.closed_at = now

    db.add(
        PaperTransaction(
            user_id=user_id,
            execution_id=position.strategy_execution_id,
            order_id=order.id,
            type=_transaction_type("exit", action),
            amount=cash_flow(action, fill_price, qty, position.lot_size),
            created_at=now,
        )
    )

    _close_journal_legs(user_id, position, qty, fill_price, db, now)

    if was_open and new_net == 0 and position.strategy_execution_id:
        execution = db.scalar(
            select(StrategyExecution).where(
                StrategyExecution.user_id == user_id,
                StrategyExecution.execution_id == position.strategy_execution_id,
            )
        )
        if execution is not None:
            execution.realized_pnl = round((execution.realized_pnl or 0.0) + realized, 2)
            execution.exit_at = now
            execution.updated_at = now

    db.commit()
    db.refresh(position)
    return ExitOut(order=_serialize_order(order), position=_serialize_position(position), duplicated=False)


def _close_journal_legs(user_id: str, position: Position, exit_qty: int, exit_price: float, db: Session, now: datetime) -> None:
    """Close the legacy journal legs backing an exit, FIFO across entry orders.

    The authoritative position math is exact regardless; this keeps the
    journal's closed-trade stats consistent. Whole-leg granularity: when an
    exit covers part of a leg, the leg is marked closed with realized P&L
    scaled to the covered quantity (the leg's original quantity is kept for
    history). This is a journal-view approximation for exotic partial
    netting; documented in PROJECT_STATUS.
    """
    entry_orders = db.scalars(
        select(PaperOrder)
        .where(
            PaperOrder.user_id == user_id,
            PaperOrder.kind == "entry",
            PaperOrder.symbol == position.symbol,
            PaperOrder.expiry == position.expiry,
            PaperOrder.strike == position.strike,
            PaperOrder.option_type == position.option_type,
            PaperOrder.status == "FILLED",
        )
        .order_by(PaperOrder.id.asc())
    ).all()

    remaining = exit_qty
    touched_trades: set[int] = set()
    for order in entry_orders:
        if remaining <= 0:
            break
        cover = min(order.quantity, remaining)
        remaining -= cover
        if order.journal_leg_id is None:
            continue
        leg = db.get(Leg, order.journal_leg_id)
        if leg is None or leg.exit_at is not None:
            continue
        leg.exit_price = exit_price
        leg.exit_at = now
        full_realized = _journal_dir(leg.action) * (exit_price - leg.premium) * leg.quantity * leg.lot_size
        leg.realized_pnl = round(full_realized * (cover / leg.quantity), 2) if leg.quantity else 0.0
        touched_trades.add(leg.trade_id)

    if touched_trades:
        trades = db.scalars(select(Trade).where(Trade.id.in_(touched_trades))).all()
        for t in trades:
            if t.status == "open" and all(l.exit_at is not None for l in t.legs):
                t.status = "closed"
                t.exit_at = now
                t.realized_pnl = round(sum(l.realized_pnl or 0.0 for l in t.legs), 2)
                t.updated_at = now


# ---- Read models (§24/§25) ---------------------------------------------------


def get_open_positions(user_id: str, db: Session) -> list[dict]:
    positions = db.scalars(
        select(Position)
        .where(Position.user_id == user_id, Position.status == "open")
        .order_by(Position.opened_at.desc())
    ).all()
    # Unrealized P&L needs a market mark — never fabricated server-side.
    return [_serialize_position(p) for p in positions]


def get_order_history(user_id: str, db: Session) -> list[dict]:
    orders = db.scalars(
        select(PaperOrder)
        .where(PaperOrder.user_id == user_id)
        .order_by(PaperOrder.created_at.desc())
    ).all()
    return [_serialize_order(o) for o in orders]


def get_portfolio(user_id: str, db: Session) -> PortfolioOut:
    account = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
    starting = account.starting_capital if account else DEFAULT_STARTING_CAPITAL

    txn_sum = db.scalar(
        select(func.coalesce(func.sum(PaperTransaction.amount), 0.0)).where(
            PaperTransaction.user_id == user_id
        )
    ) or 0.0

    positions = list(db.scalars(select(Position).where(Position.user_id == user_id)).all())
    realized = round(sum(p.realized_pnl for p in positions), 2)
    open_positions = [p for p in positions if p.status == "open"]
    invested = round(
        sum(p.average_entry_price * abs(p.net_quantity) * p.lot_size for p in open_positions), 2
    )
    open_execs = {p.strategy_execution_id for p in open_positions if p.strategy_execution_id}

    summary = PortfolioSummaryOut(
        starting_cash=round(starting, 2),
        available_cash=round(starting + txn_sum, 2),
        invested_value=invested,
        realized_pnl=realized,
        unrealized_pnl=None,  # requires market marks (the UI applies them)
        total_pnl=realized,
        open_position_count=len(open_positions),
        open_strategy_count=len(open_execs),
    )
    return PortfolioOut(summary=summary, groups=get_portfolio_groups(user_id, db))


def get_portfolio_groups(user_id: str, db: Session) -> list[PortfolioGroupOut]:
    """Strategy-grouped view: every execution with its orders and P&L."""
    executions = db.scalars(
        select(StrategyExecution)
        .where(StrategyExecution.user_id == user_id)
        .order_by(StrategyExecution.entry_at.desc())
    ).all()
    positions = list(db.scalars(select(Position).where(Position.user_id == user_id)).all())
    orders = list(db.scalars(select(PaperOrder).where(PaperOrder.user_id == user_id)).all())

    groups = []
    for ex in executions:
        ex_orders = [o for o in orders if o.execution_id == ex.execution_id]
        ex_positions = [p for p in positions if p.strategy_execution_id == ex.execution_id]
        realized = round(sum(p.realized_pnl for p in ex_positions), 2)
        groups.append(
            PortfolioGroupOut(
                execution_id=ex.execution_id,
                strategy_tag=ex.strategy_tag,
                symbol=ex.symbol,
                status=ex.status,
                entry_net=ex.entry_net,
                realized_pnl=realized,
                legs=[_serialize_order(o) for o in ex_orders],
                entry_at=ex.entry_at,
            )
        )
    return groups


def reconcile(user_id: str, db: Session) -> ReconcileOut:
    """Validate that orders, positions, cash and executions agree.

    Returns structured discrepancies; never silently repairs data.
    """
    discrepancies: list[dict] = []
    positions = list(db.scalars(select(Position).where(Position.user_id == user_id)).all())
    orders = list(db.scalars(select(PaperOrder).where(PaperOrder.user_id == user_id)).all())
    executions = list(
        db.scalars(select(StrategyExecution).where(StrategyExecution.user_id == user_id)).all()
    )

    # 1. Position quantities agree with fills; 2. realized agrees with exits.
    for p in positions:
        instr_orders = [
            o for o in orders
            if o.symbol == p.symbol and o.expiry == p.expiry
            and o.strike == p.strike and o.option_type == p.option_type
        ]
        expected_net = sum(
            o.filled_quantity if o.action == "buy" else -o.filled_quantity for o in instr_orders
        )
        if expected_net != p.net_quantity:
            discrepancies.append(
                {
                    "type": "POSITION_QUANTITY_MISMATCH",
                    "position_id": p.id,
                    "expected": expected_net,
                    "actual": p.net_quantity,
                }
            )
        expected_realized = round(sum(o.realized_pnl or 0.0 for o in instr_orders if o.kind == "exit"), 2)
        if abs(expected_realized - p.realized_pnl) > 0.005:
            discrepancies.append(
                {
                    "type": "REALIZED_PNL_MISMATCH",
                    "position_id": p.id,
                    "expected": expected_realized,
                    "actual": p.realized_pnl,
                }
            )

    # 3. Cash agrees with the recorded ledger: the sum of ledger amounts must
    # equal the sum of the cash flows of every filled order (catches missing
    # or double-written transactions).
    txn_sum = db.scalar(
        select(func.coalesce(func.sum(PaperTransaction.amount), 0.0)).where(
            PaperTransaction.user_id == user_id
        )
    ) or 0.0
    expected_cash_flow = round(
        sum(
            cash_flow(o.action, o.fill_price, o.filled_quantity, o.lot_size)
            for o in orders
            if o.status == "FILLED" and o.fill_price is not None
        ),
        2,
    )
    if abs(round(txn_sum, 2) - expected_cash_flow) > 0.005:
        discrepancies.append(
            {
                "type": "CASH_MISMATCH",
                "expected": expected_cash_flow,
                "actual": round(txn_sum, 2),
            }
        )

    # 4. No duplicate executions.
    if len({e.execution_id for e in executions}) != len(executions):
        discrepancies.append({"type": "DUPLICATE_EXECUTION_ID", "expected": len(executions)})
    if len({e.client_order_id for e in executions}) != len(executions):
        discrepancies.append({"type": "DUPLICATE_CLIENT_ORDER_ID", "expected": len(executions)})
    if len({o.client_order_id for o in orders}) != len(orders):
        discrepancies.append({"type": "DUPLICATE_ORDER_CLIENT_ORDER_ID", "expected": len(orders)})

    return ReconcileOut(valid=not discrepancies, discrepancies=discrepancies)


def reset_portfolio(user_id: str, db: Session) -> PortfolioOut:
    """Clear the user's authoritative paper state (keeps the account record)."""
    from sqlalchemy import delete

    for model in (PaperOrder, Position, PaperTransaction, StrategyExecution):
        db.execute(delete(model).where(model.user_id == user_id))
    trades = db.scalars(select(Trade).where(Trade.user_id == user_id)).all()
    for t in trades:
        for leg in list(t.legs):
            db.delete(leg)
        db.delete(t)
    db.commit()
    return get_portfolio(user_id, db)


def _execution_out(execution: StrategyExecution, db: Session, duplicated: bool) -> ExecutionOut:
    orders = list(
        db.scalars(
            select(PaperOrder)
            .where(PaperOrder.execution_id == execution.execution_id)
            .order_by(PaperOrder.id.asc())
        ).all()
    )
    filled = sum(1 for o in orders if o.status == "FILLED")
    return ExecutionOut(
        execution_id=execution.execution_id,
        status=execution.status,
        symbol=execution.symbol,
        strategy_tag=execution.strategy_tag,
        entry_net=execution.entry_net,
        orders=[_serialize_order(o) for o in orders],
        filled_count=filled,
        failed_count=len(orders) - filled,
        errors=[],
        duplicated=duplicated,
    )
