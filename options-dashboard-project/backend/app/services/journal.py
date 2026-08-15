"""Paper trading journal service.

The auto-log controller that the paper trading engine calls on every fill and
every close. All money math works in rupees and handles multi-leg strategies
(spreads, condors, ...) by treating each leg's premium flow with its sign
(+buy / -sell), so the net credit of a short vertical spread is captured both
at entry (entry_net) and when the position closes (realized P&L).
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaperAccount, Trade, Leg
from app.schemas import OrderFillIn, TradeOut

DEFAULT_STARTING_CAPITAL = 500000


class TradeNotFoundError(Exception):
    pass


class LegNotFoundError(Exception):
    pass


class TradeClosedError(Exception):
    pass


def _direction(action: str) -> int:
    """Premium-flow direction, matching the frontend builder's convention.

    Buying pays out (+1), selling brings money in (-1). Summed over the legs,
    a negative value is a net credit received (you sold more premium than you
    bought — a short vertical spread), a positive value is a net debit paid
    (a long spread).
    """
    return -1 if action == "sell" else 1


def _leg_money(leg: Leg, price: float) -> float:
    """Rupee cash flow for one leg at `price`: direction x price x qty x lot size."""
    return _direction(leg.action) * price * leg.quantity * leg.lot_size


def handlePaperOrderFill(user_id: str, order_details: OrderFillIn, db: Session) -> Trade:
    """Auto-logs an executed paper trade into the `trades` and `legs` tables.

    Creates the trade row plus one leg row per option, computes the strategy's
    net entry debit/credit (multi-leg aware), and ensures the user's simulated
    account record exists.
    """
    now = datetime.now(timezone.utc)
    symbol = order_details.symbol.upper()

    account = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
    if account is None:
        account = PaperAccount(
            user_id=user_id,
            starting_capital=order_details.starting_capital or DEFAULT_STARTING_CAPITAL,
        )
        db.add(account)
    elif order_details.starting_capital is not None:
        account.starting_capital = order_details.starting_capital
        account.updated_at = now

    trade = Trade(
        user_id=user_id,
        symbol=symbol,
        strategy_tag=order_details.strategy_tag or "Custom",
        status="open",
        entry_net=0.0,
        entry_at=now,
    )
    db.add(trade)
    db.flush()  # assign trade.id for the leg foreign keys

    legs = []
    for leg_in in order_details.legs:
        leg = Leg(
            trade_id=trade.id,
            symbol=leg_in.symbol.upper(),
            expiration_date=leg_in.expiration_date,
            strike_price=leg_in.strike_price,
            option_type=leg_in.option_type,
            action=leg_in.action,
            premium=leg_in.premium,
            quantity=leg_in.quantity,
            lot_size=leg_in.lot_size,
            entry_at=now,
        )
        db.add(leg)
        legs.append(leg)

    trade.entry_net = round(sum(_leg_money(l, l.premium) for l in legs), 2)
    db.commit()
    db.refresh(trade)
    return trade


def close_leg(user_id: str, trade_id: int, leg_id: int, exit_price: float, db: Session) -> Trade:
    """Records an exit price for one leg of a paper trade.

    When the last open leg is closed, the whole trade is marked closed and its
    realized P&L is the sum of the legs' realized P&L — which is exactly the
    net credit received at entry minus the net debit paid at exit for spreads.
    """
    trade = db.get(Trade, trade_id)
    if trade is None or trade.user_id != user_id:
        raise TradeNotFoundError("Trade not found")
    if trade.status == "closed":
        raise TradeClosedError("Trade already closed")

    leg = next((l for l in trade.legs if l.id == leg_id), None)
    if leg is None:
        raise LegNotFoundError("Leg not found")

    now = datetime.now(timezone.utc)
    leg.exit_price = exit_price
    leg.exit_at = now
    leg.realized_pnl = round(_leg_money(leg, exit_price) - _leg_money(leg, leg.premium), 2)

    if all(l.exit_at is not None for l in trade.legs):
        trade.status = "closed"
        trade.exit_at = now
        trade.realized_pnl = round(sum(l.realized_pnl or 0.0 for l in trade.legs), 2)
        trade.updated_at = now

    db.commit()
    db.refresh(trade)
    return trade


def get_journal(user_id: str, db: Session) -> dict:
    """Returns the user's journal: account, performance stats, and trade log."""
    account = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
    trades = list(
        db.scalars(
            select(Trade).where(Trade.user_id == user_id).order_by(Trade.entry_at.desc())
        ).all()
    )

    closed = [t for t in trades if t.status == "closed"]
    realized = [t.realized_pnl or 0.0 for t in closed]
    gross_profit = round(sum(x for x in realized if x > 0), 2)
    gross_loss = round(sum(-x for x in realized if x < 0), 2)
    wins = sum(1 for x in realized if x > 0)
    net_pnl = round(sum(realized), 2)

    starting = account.starting_capital if account else DEFAULT_STARTING_CAPITAL

    stats = {
        "total_trades": len(trades),
        "open_trades": sum(1 for t in trades if t.status == "open"),
        "closed_trades": len(closed),
        "wins": wins,
        "win_rate": round(wins / len(closed), 4) if closed else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }

    return {
        "account": {
            "starting_capital": starting,
            "balance": round(starting + net_pnl, 2),
            "net_pnl": net_pnl,
        },
        "stats": stats,
        "trades": [TradeOut.model_validate(t).model_dump(mode="json") for t in trades],
    }
