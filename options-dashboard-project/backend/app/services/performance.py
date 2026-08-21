"""Phase 5.1 — Portfolio & Journal Analytics (server-authoritative).

This service derives every performance metric from the Phase 5.0
authoritative paper-trading records (``StrategyExecution``, ``Position``,
``PaperOrder``, ``PaperTransaction``, ``PaperAccount``). It never mutates
trading state and never fabricates values:

- Realized P&L of a completed strategy trade = the SUM of its positions'
  ``realized_pnl`` (positions aggregate partial AND full exits exactly; the
  legacy journal rows are a secondary view and are never double-counted).
- A strategy execution counts as ONE completed trade once ALL of its
  positions are closed (no open legs remain). Pending/rejected/cancelled
  orders and open strategies are never counted.
- Unrealized P&L requires market marks. The backend has no live marks, so
  ``unrealized_pnl`` stays ``None`` and ``current_marks`` is reported as
  ``unavailable``; the frontend overlays its chain-cache marks for display
  (the platform's existing market-data path).
- Historical unrealized P&L is NOT stored anywhere, so the equity curve and
  daily P&L are REALIZED-only and labeled as such. Nothing is back-filled.

Pure helpers are exported for direct testing; ``get_analytics`` assembles
the full response for ``GET /paper/analytics``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PaperAccount, PaperOrder, PaperTransaction, Position, StrategyExecution
from app.services.paper_execution import DEFAULT_STARTING_CAPITAL, reconcile


def _parse_tags(raw: str | None) -> list[str] | None:
    """Parse a JSON array of tag strings from the database column.

    Returns None when the column is empty/null. Returns an empty list when
    the column contains ``[]``. Returns a filtered list of non-empty strings
    when the column contains valid JSON. Falls back to None for malformed data.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(t) for t in parsed if t]
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def serialize_tags(tags: list[str] | None) -> str | None:
    """Serialize a list of tag strings to a JSON string for storage."""
    if not tags:
        return None
    cleaned = [str(t).strip() for t in tags if t and str(t).strip()]
    return json.dumps(cleaned) if cleaned else None

# ---- Pure classification ----------------------------------------------------


def classify_result(realized_pnl: float | None) -> str | None:
    """WIN / LOSS / BREAKEVEN for a COMPLETED trade, from realized P&L only.

    A completed trade is never classified from unrealized P&L. ``None`` is
    returned for trades without a valid realized value (not completed).
    """
    if realized_pnl is None:
        return None
    if realized_pnl > 0:
        return "WIN"
    if realized_pnl < 0:
        return "LOSS"
    return "BREAKEVEN"


def win_rate(wins: int, total: int) -> float | None:
    """winRate = winningTrades / totalCompletedTrades × 100.

    Returns ``None`` (not 0) when there are no completed trades.
    """
    if not total:
        return None
    return round(wins / total * 100, 2)


def average_winner(pnls: list[float]) -> float | None:
    """Mean of winning P&Ls; ``None`` when there are no winners."""
    wins = [p for p in pnls if p is not None and p > 0]
    if not wins:
        return None
    return round(sum(wins) / len(wins), 2)


def average_loser(pnls: list[float]) -> float | None:
    """Mean of losing P&Ls (stays negative); ``None`` when there are no losers."""
    losses = [p for p in pnls if p is not None and p < 0]
    if not losses:
        return None
    return round(sum(losses) / len(losses), 2)


def profit_factor(pnls: list[float]) -> float | None:
    """grossProfit / abs(grossLoss). ``None`` when either side is zero/absent —
    never ``Infinity``."""
    gross_profit = sum(p for p in pnls if p is not None and p > 0)
    gross_loss = abs(sum(p for p in pnls if p is not None and p < 0))
    if gross_profit == 0 or gross_loss == 0:
        return None
    return round(gross_profit / gross_loss, 4)


def expectancy(pnls: list[float]) -> float | None:
    """(winRateDecimal × averageWinner) + (lossRateDecimal × averageLoser).

    Breakeven trades are counted in the denominator and contribute zero to
    both sides. ``None`` when there are no completed trades at all.
    """
    if not pnls:
        return None
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    win_rate_dec = len(wins) / n
    loss_rate_dec = len(losses) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return round(win_rate_dec * avg_win + loss_rate_dec * avg_loss, 2)


def largest_winner(pnls: list[float]) -> float | None:
    return round(max(pnls), 2) if pnls else None


def largest_loser(pnls: list[float]) -> float | None:
    return round(min(pnls), 2) if pnls else None


def streaks(results: list[str | None]) -> dict:
    """Current and maximum win/loss streaks over CHRONOLOGICAL completed trades.

    A BREAKEVEN breaks both a win and a loss run (it is neither), so a win
    immediately after a breakeven starts a fresh streak of 1.
    """
    max_win = max_loss = 0
    run = 0
    run_kind: str | None = None
    for r in results:
        kind = "win" if r == "WIN" else ("loss" if r == "LOSS" else None)
        if kind is None:
            run, run_kind = 0, None
        elif kind == run_kind:
            run += 1
        else:
            run, run_kind = 1, kind
        if run_kind == "win":
            max_win = max(max_win, run)
        elif run_kind == "loss":
            max_loss = max(max_loss, run)

    # Current streaks = the trailing run only (breakeven or the opposite type
    # ends it).
    cur_win = cur_loss = 0
    if results:
        last = results[-1]
        if last == "WIN":
            for r in reversed(results):
                if r != "WIN":
                    break
                cur_win += 1
        elif last == "LOSS":
            for r in reversed(results):
                if r != "LOSS":
                    break
                cur_loss += 1
    return {
        "current_win_streak": cur_win,
        "current_loss_streak": cur_loss,
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
    }


def _as_utc(dt: datetime) -> datetime:
    """SQLite stores naive datetimes; treat them as UTC for duration math."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def holding_duration_seconds(entry_at: datetime | None, exit_at: datetime | None) -> float | None:
    """Holding duration in seconds for a completed trade; ``None`` when either
    timestamp is missing/invalid (never fabricated)."""
    if not entry_at or not exit_at:
        return None
    try:
        seconds = (_as_utc(exit_at) - _as_utc(entry_at)).total_seconds()
        return round(seconds, 2) if seconds >= 0 else None
    except (TypeError, ValueError):
        return None


def duration_stats(durations: list[float]) -> dict:
    """avg/median/shortest/longest holding durations (seconds), or ``None``
    for every field when no valid durations exist."""
    empty = {
        "average_holding_duration": None,
        "median_holding_duration": None,
        "shortest_holding_duration": None,
        "longest_holding_duration": None,
    }
    if not durations:
        return empty
    return {
        "average_holding_duration": round(sum(durations) / len(durations), 2),
        "median_holding_duration": round(median(durations), 2),
        "shortest_holding_duration": round(min(durations), 2),
        "longest_holding_duration": round(max(durations), 2),
    }


def format_duration(seconds: float | None) -> str | None:
    """User-friendly duration label: ``2h 14m``, ``45m``, ``30s``, ``3d 4h``."""
    if seconds is None:
        return None
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h = m // 60
    if h < 24:
        return f"{h}h {m % 60}m"
    d = h // 24
    return f"{d}d {h % 24}h"


# ---- Pure curve / grouping helpers ------------------------------------------


def equity_curve(starting_capital: float, completed_trades: list[dict]) -> list[dict]:
    """REALIZED equity curve from chronologically ordered completed trades.

    Each point: ``{date, pnl, cumulative_pnl, equity}`` where
    ``equity = starting_capital + cumulative realized P&L``, dated by the
    trade's exit (realization) day. A baseline point at starting capital is
    prepended. Historical unrealized marks are NOT fabricated, so the curve
    is explicitly realized-only (the UI labels it "Realized Equity Curve").
    """
    if not completed_trades:
        return []
    points = []
    cumulative = 0.0
    baseline_date = completed_trades[0]["exit_date"]
    points.append(
        {
            "date": baseline_date,
            "pnl": 0.0,
            "cumulative_pnl": 0.0,
            "equity": round(starting_capital, 2),
        }
    )
    for t in completed_trades:
        cumulative += t["realized_pnl"] or 0.0
        points.append(
            {
                "date": t["exit_date"],
                "pnl": round(t["realized_pnl"] or 0.0, 2),
                "cumulative_pnl": round(cumulative, 2),
                "equity": round(starting_capital + cumulative, 2),
            }
        )
    return points


def drawdown(equity_points: list[dict]) -> dict:
    """Drawdown from an equity curve; ``None`` fields for empty curves."""
    empty = {
        "current_drawdown": None,
        "current_drawdown_pct": None,
        "max_drawdown": None,
        "max_drawdown_pct": None,
    }
    if not equity_points:
        return empty
    peak = equity_points[0]["equity"]
    max_dd = 0.0
    max_dd_pct = 0.0
    for p in equity_points:
        equity = p["equity"]
        peak = max(peak, equity)
        dd = equity - peak  # <= 0
        dd_pct = (dd / peak * 100) if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
    last = equity_points[-1]["equity"]
    current = round(last - peak, 2)
    return {
        "current_drawdown": current,
        "current_drawdown_pct": round(current / peak * 100, 2) if peak > 0 else None,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
    }


def daily_pnl(completed_trades: list[dict]) -> list[dict]:
    """Realized P&L grouped by exit date.

    Historical unrealized P&L was never stored, so it is reported as
    ``None`` (unavailable) and only the realized component is returned,
    clearly labeled.
    """
    by_date: dict[str, float] = {}
    for t in completed_trades:
        d = t["exit_date"]
        by_date[d] = round(by_date.get(d, 0.0) + (t["realized_pnl"] or 0.0), 2)
    return [
        {"date": d, "realized_pnl": v, "unrealized_pnl": None, "total_pnl": v}
        for d, v in sorted(by_date.items())
    ]


def strategy_grouping(completed_trades: list[dict]) -> list[dict]:
    """Group completed strategy trades by strategy tag (one strategy = one row).

    Uses the existing strategy identity (``strategy_tag``); no new strategy
    model is created. Sorted by total P&L descending.
    """
    groups: dict[str, list[float]] = {}
    for t in completed_trades:
        groups.setdefault(t["strategy"] or "Custom", []).append(t["realized_pnl"] or 0.0)
    rows = []
    for name, pnls in groups.items():
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        total = round(sum(pnls), 2)
        rows.append(
            {
                "strategy": name,
                "trades": len(pnls),
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate(wins, len(pnls)),
                "total_pnl": total,
                "average_pnl": round(total / len(pnls), 2),
                "profit_factor": profit_factor(pnls),
                "expectancy": expectancy(pnls),
            }
        )
    return sorted(rows, key=lambda r: -r["total_pnl"])


def position_exposure(positions: list) -> dict:
    """Long/short exposure of OPEN positions at their average entry value.

    Long exposure = Σ avg_entry × qty × lot for longs; short exposure = the
    same for shorts (absolute). These are entry-value exposures, NOT margin
    requirements, and are labeled as such.
    """
    long_exposure = sum(
        p.average_entry_price * p.net_quantity * p.lot_size
        for p in positions
        if p.net_quantity > 0
    )
    short_exposure = sum(
        p.average_entry_price * abs(p.net_quantity) * p.lot_size
        for p in positions
        if p.net_quantity < 0
    )
    return {
        "long_exposure": round(long_exposure, 2),
        "short_exposure": round(short_exposure, 2),
        "total_exposure": round(long_exposure + short_exposure, 2),
    }


# ---- Server-authoritative assembly ------------------------------------------


def get_analytics(
    user_id: str,
    db: Session,
    date_from: str | None = None,
    date_to: str | None = None,
    strategy: str | None = None,
) -> dict:
    """Assemble the full analytics response for one user.

    Completed strategy trades = executions whose positions are ALL closed.
    ``date_from`` / ``date_to`` (YYYY-MM-DD) and ``strategy`` (tag) filter
    the completed-trade set used for performance / equity / drawdown /
    strategies / journal; the canonical summary always reflects the full
    portfolio.
    """
    account = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
    starting = account.starting_capital if account else DEFAULT_STARTING_CAPITAL

    txn_sum = db.scalar(
        select(func.coalesce(func.sum(PaperTransaction.amount), 0.0)).where(
            PaperTransaction.user_id == user_id
        )
    ) or 0.0

    positions = list(db.scalars(select(Position).where(Position.user_id == user_id)).all())
    executions = list(
        db.scalars(
            select(StrategyExecution)
            .where(StrategyExecution.user_id == user_id)
            .order_by(StrategyExecution.entry_at.asc())
        ).all()
    )
    orders = list(db.scalars(select(PaperOrder).where(PaperOrder.user_id == user_id)).all())

    open_positions = [p for p in positions if p.status == "open"]
    invested = round(
        sum(p.average_entry_price * abs(p.net_quantity) * p.lot_size for p in open_positions), 2
    )
    realized_total = round(sum(p.realized_pnl for p in positions), 2)
    open_execs = {p.strategy_execution_id for p in open_positions if p.strategy_execution_id}

    # Completed strategy trades — authoritative realized = Σ position.realized_pnl
    # (positions include partial + full exits; journal rows are NOT double-counted).
    completed: list[dict] = []
    for ex in executions:
        ex_positions = [p for p in positions if p.strategy_execution_id == ex.execution_id]
        if not ex_positions:
            continue
        if any(p.status == "open" for p in ex_positions):
            continue  # strategy still running — not a completed trade
        exit_at = ex.exit_at or max(
            (p.closed_at for p in ex_positions if p.closed_at), default=None
        )
        if exit_at is None:
            continue  # closed positions without a timestamp cannot be a completed trade
        completed.append(
            {
                "execution_id": ex.execution_id,
                "strategy": ex.strategy_tag or "Custom",
                "symbol": ex.symbol,
                "entry_at": ex.entry_at,
                "exit_at": exit_at,
                "exit_date": _as_utc(exit_at).date().isoformat(),
                "realized_pnl": round(sum(p.realized_pnl for p in ex_positions), 2),
                "result": classify_result(round(sum(p.realized_pnl for p in ex_positions), 2)),
                "legs": [o for o in orders if o.execution_id == ex.execution_id],
                "tags": _parse_tags(ex.tags),
                "notes": ex.notes,
            }
        )

    # Optional filters (applied against authoritative server data).
    if date_from:
        completed = [t for t in completed if t["exit_date"] >= date_from]
    if date_to:
        completed = [t for t in completed if t["exit_date"] <= date_to]
    if strategy:
        target = strategy.strip().lower()
        completed = [t for t in completed if t["strategy"].lower() == target]

    pnls = [t["realized_pnl"] for t in completed]
    results = [t["result"] for t in completed]
    durations = [
        d
        for d in (holding_duration_seconds(t["entry_at"], t["exit_at"]) for t in completed)
        if d is not None
    ]
    wins = sum(1 for r in results if r == "WIN")
    losses = sum(1 for r in results if r == "LOSS")

    performance = {
        "total_completed_trades": len(completed),
        "winning_trades": wins,
        "losing_trades": losses,
        "breakeven_trades": sum(1 for r in results if r == "BREAKEVEN"),
        "win_rate": win_rate(wins, len(completed)),
        "average_winner": average_winner(pnls),
        "average_loser": average_loser(pnls),
        "profit_factor": profit_factor(pnls),
        "expectancy": expectancy(pnls),
        "largest_winner": largest_winner(pnls),
        "largest_loser": largest_loser(pnls),
        **streaks(results),
        **duration_stats(durations),
    }

    curve = equity_curve(starting, completed)
    dd = drawdown(curve)

    total_pnl = round(realized_total, 2)  # unrealized unavailable server-side (None)
    summary = {
        "starting_capital": round(starting, 2),
        "available_cash": round(starting + txn_sum, 2),
        "invested_value": invested,
        "realized_pnl": realized_total,
        "unrealized_pnl": None,
        "total_pnl": total_pnl,
        "return_pct": round(total_pnl / starting * 100, 2) if starting > 0 else None,
        "open_position_count": len(open_positions),
        "open_strategy_count": len(open_execs),
    }

    journal_rows = []
    for t in reversed(completed):  # newest first
        dur = holding_duration_seconds(t["entry_at"], t["exit_at"])
        journal_rows.append(
            {
                "execution_id": t["execution_id"],
                "strategy": t["strategy"],
                "symbol": t["symbol"],
                "entry_at": t["entry_at"],
                "exit_at": t["exit_at"],
                "duration_seconds": dur,
                "duration_label": format_duration(dur),
                "realized_pnl": t["realized_pnl"],
                "result": t["result"],
                "legs": [_leg_summary(o) for o in t["legs"]],
                "tags": t.get("tags"),
                "notes": t.get("notes"),
            }
        )

    exposure = position_exposure(open_positions)
    position_items = [
        {
            "symbol": p.symbol,
            "expiry": p.expiry,
            "strike": p.strike,
            "option_type": p.option_type,
            "net_quantity": p.net_quantity,
            "average_entry": p.average_entry_price,
            "current_price": None,
            "unrealized_pnl": None,
            "market_value": None,
            "strategy_execution_id": p.strategy_execution_id,
        }
        for p in sorted(open_positions, key=lambda x: x.symbol)
    ]

    warnings = []
    rec = reconcile(user_id, db)
    if not rec.valid:
        warnings.append(
            {"code": "PORTFOLIO_DATA_INCONSISTENT", "discrepancies": rec.discrepancies}
        )

    return {
        "summary": summary,
        "performance": performance,
        "equity_curve": curve,
        "drawdown": dd,
        "daily_pnl": daily_pnl(completed),
        "strategies": strategy_grouping(completed),
        "positions": {**exposure, "items": position_items},
        "journal": journal_rows,
        "data_quality": {
            "historical_unrealized": "unavailable",  # no historical marks are stored
            "current_marks": "unavailable",  # backend has no live marks (frontend chain cache)
            "completed_trades": "available" if completed else "none",
            "warnings": warnings,
        },
        "filters": {
            "date_from": date_from,
            "date_to": date_to,
            "strategy": strategy,
        },
    }


def _leg_summary(order) -> dict:
    """One leg of a completed strategy trade for the grouped journal view."""
    return {
        "symbol": order.symbol,
        "expiry": order.expiry,
        "strike": order.strike,
        "option_type": order.option_type,
        "action": order.action,
        "quantity": order.quantity,
        "lot_size": order.lot_size,
        "fill_price": order.fill_price,
    }
