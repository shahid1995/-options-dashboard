"""Phase 6.0 — Capital & Margin Foundation (server-authoritative).

This service builds the foundational capital abstraction WITHOUT a SPAN /
exposure-margin calculator. It keeps five concepts strictly separate:

- PREMIUM OUTLAY   — option premium actually paid on long (buy) legs.
- BROKER MARGIN    — margin requirement explicitly reported by a connected
                     broker (the current Upstox integration has NO margin or
                     funds endpoint, so this stays unavailable — never
                     invented).
- ESTIMATED CAPITAL— a model-derived analytical estimate. Phase 6.0 only
                     supports the deterministic premium basis for DEFINED-DEBIT
                     strategies. Credit strategies receiving premium at entry
                     are NOT assigned estimated capital (premium received is
                     not capital required).
- AVAILABLE FUNDS  — funds available per the authoritative account/broker
                     source (broker funds stay unavailable; paper cash is
                     exposed separately, never renamed as broker funds).
- PAPER CAPITAL    — the paper account's starting capital and available cash
                     (cash-ledger derived), labeled as paper values.

Every figure carries its source (BROKER_REPORTED | ESTIMATED | CALCULATED |
UNAVAILABLE) and its availability status (available | partial | unavailable).
Missing values are null, never 0. No Return-on-Capital metric is computed in
this phase; only its future inputs are prepared (see
``capital_efficiency_inputs``).

Whole-strategy scope (§17): capital analysis operates on the FULL strategy
execution (all of its legs share one ``strategy_execution_id``); the broker
provider receives the complete open strategy set as context and is never asked
to sum unrelated per-leg numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PaperAccount, PaperOrder, PaperTransaction, Position, StrategyExecution
from app.services.paper_execution import DEFAULT_STARTING_CAPITAL

# ---- Source classification (§3) ---------------------------------------------
SOURCE_BROKER_REPORTED = "BROKER_REPORTED"
SOURCE_ESTIMATED = "ESTIMATED"
SOURCE_CALCULATED = "CALCULATED"
SOURCE_UNAVAILABLE = "UNAVAILABLE"

# ---- Availability status (§12) ----------------------------------------------
STATUS_AVAILABLE = "available"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"

# Estimated-capital basis labels (§8).
BASIS_PREMIUM = "premium"

# ---- Pure number rules (§23-11/12) ------------------------------------------


def is_valid_number(value) -> bool:
    """A valid capital figure: a finite number. None / NaN / Infinity are
    NEVER valid — missing stays missing (null), never silently 0."""
    return value is not None and isinstance(value, (int, float)) and isfinite(value)


def capital_value(value, source: str) -> dict:
    """Canonical ``{value, source, status}`` triple for one capital figure.

    A finite value → status ``available``. Anything else → ``value: null``
    with status ``unavailable`` (missing is never converted to 0).
    """
    if is_valid_number(value):
        return {"value": round(value, 2), "source": source, "status": STATUS_AVAILABLE}
    return {"value": None, "source": source, "status": STATUS_UNAVAILABLE}


# ---- Premium (§5) -----------------------------------------------------------

def premium_outlay_for_orders(orders) -> float:
    """Gross premium PAID on long (buy) entry legs of ONE strategy execution.

    Sum of ``fill_price × filled_quantity × lot_size`` over FILLED buy entry
    orders — the cash actually paid for the options bought. This is a
    CALCULATED figure (0 is a valid premium outlay for a pure-credit strategy
    with no long legs) and it is NOT broker margin and NOT estimated capital.
    """
    return round(
        sum(
            o.fill_price * o.filled_quantity * o.lot_size
            for o in orders
            if o.kind == "entry"
            and o.action == "buy"
            and o.status == "FILLED"
            and is_valid_number(o.fill_price)
        ),
        2,
    )


# ---- Estimated capital (§8/§9) -----------------------------------------------

def estimate_capital_for_execution(entry_net) -> dict:
    """Estimated capital for ONE whole strategy execution.

    Defined-debit strategies (net debit > 0) get the premium-basis estimate:
    the strategy's NET premium paid at entry (``entry_net``). Credit
    strategies and zero-flow strategies return ``value: null`` — premium
    received at entry is NOT capital required, and no valid analytical model
    exists yet (Phase 6.1+). Never pretend premium received equals margin.
    """
    if is_valid_number(entry_net) and entry_net > 0:
        return {"value": round(entry_net, 2), "basis": BASIS_PREMIUM}
    return {"value": None, "basis": None}


def aggregate_estimates(estimates: list[dict]) -> dict:
    """Combine per-strategy estimated-capital values across the portfolio.

    - every open strategy has an estimate  → available (sum)
    - some have estimates                  → partial (sum of the available ones)
    - none                                 → unavailable (null)
    """
    values = [e["value"] for e in estimates if is_valid_number(e.get("value"))]
    if not values:
        return {"value": None, "source": SOURCE_ESTIMATED, "status": STATUS_UNAVAILABLE}
    if len(values) < len(estimates):
        return {"value": round(sum(values), 2), "source": SOURCE_ESTIMATED, "status": STATUS_PARTIAL}
    return {"value": round(sum(values), 2), "source": SOURCE_ESTIMATED, "status": STATUS_AVAILABLE}


# ---- Future Return-on-Capital inputs (§15/§16) -------------------------------

def capital_efficiency_inputs(realized_pnl, unrealized_pnl, capital_used) -> dict:
    """Future Return-on-Capital INPUTS ONLY — the metric is NOT computed here.

    Returns ``{pnl, capital_used, available}``:

    - ``capital_used`` is the estimated capital engaged in open strategies.
    - ``pnl`` = realized + unrealized; unrealized may be None (no market
      mark), in which case pnl is realized-only.
    - ``available`` is False whenever any required input is missing, so a
      future phase can never divide by an unknown denominator.
    """
    if not is_valid_number(capital_used):
        return {"pnl": None, "capital_used": None, "available": False}
    if is_valid_number(unrealized_pnl):
        pnl = round(realized_pnl + unrealized_pnl, 2) if is_valid_number(realized_pnl) else None
    else:
        pnl = realized_pnl if is_valid_number(realized_pnl) else None
    return {"pnl": pnl, "capital_used": round(capital_used, 2), "available": pnl is not None}


# ---- Broker provider abstraction (§6/§7/§18) --------------------------------


class MarginProvider:
    """Broker margin / funds provider interface.

    A provider answers ONE question for an authenticated user's FULL strategy
    set: "what does the broker explicitly report about margin and available
    funds?" It never computes a margin model itself (no SPAN / exposure
    calculator in Phase 6.0). Broker-specific implementations live behind
    this interface, so the capital domain never depends on Upstox naming.

    ``context`` contains ``user_id``, ``broker``, the open ``strategies``
    (whole-strategy, multi-leg) and the ``account`` record. Return shape::

        {
            "broker_margin": float | None,
            "broker_available_funds": float | None,
            "source": "BROKER_REPORTED",
            "status": "available" | "unavailable",
            "timestamp": iso-string | None,
        }
    """

    async def get_capital_snapshot(self, context: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class UnavailableMarginProvider(MarginProvider):
    """Default provider for the current integration.

    The Upstox integration exposes chains, contracts and market status only —
    NO margin or funds endpoint (§7). The honest answer is
    ``BROKER_REPORTED = unavailable``: we never fabricate a broker margin
    number, and paper cash is never relabeled as broker funds.
    """

    async def get_capital_snapshot(self, context: dict) -> dict:
        return {
            "broker_margin": None,
            "broker_available_funds": None,
            "source": SOURCE_BROKER_REPORTED,
            "status": STATUS_UNAVAILABLE,
            "timestamp": None,
        }


class StaticMarginProvider(MarginProvider):
    """Test/example provider returning fixed broker-reported values.

    Demonstrates that the abstraction surfaces broker data as BROKER_REPORTED
    without the domain depending on any particular broker. A real Phase 6.1
    implementation (Upstox funds/margin endpoints) would subclass
    ``MarginProvider`` the same way.
    """

    def __init__(self, broker_margin=None, broker_available_funds=None, timestamp=None):
        self.broker_margin = broker_margin
        self.broker_available_funds = broker_available_funds
        self.timestamp = timestamp

    async def get_capital_snapshot(self, context: dict) -> dict:
        return {
            "broker_margin": self.broker_margin,
            "broker_available_funds": self.broker_available_funds,
            "source": SOURCE_BROKER_REPORTED,
            "status": STATUS_AVAILABLE
            if (is_valid_number(self.broker_margin) or is_valid_number(self.broker_available_funds))
            else STATUS_UNAVAILABLE,
            "timestamp": self.timestamp,
        }


# ---- Capital summary --------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_capital_summary(user_id: str, db: Session, provider: MarginProvider | None = None) -> dict:
    """Server-authoritative capital summary for ONE authenticated user.

    Derived entirely from the user's own Phase 5.0 records (paper account,
    cash ledger, positions, strategy executions + their entry orders) plus the
    broker provider snapshot. Read-only; never mutates trading state; always
    available regardless of market status. User isolation: every query is
    scoped by ``user_id`` — user B can never see user A's capital.

    Only OPEN strategies engage capital: a strategy whose positions are all
    closed no longer contributes premium outlay or estimated capital.
    """
    provider = provider or UnavailableMarginProvider()

    account = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
    starting = account.starting_capital if account else DEFAULT_STARTING_CAPITAL

    txn_sum = db.scalar(
        select(func.coalesce(func.sum(PaperTransaction.amount), 0.0)).where(
            PaperTransaction.user_id == user_id
        )
    ) or 0.0
    available_cash = round(starting + txn_sum, 2)

    positions = list(db.scalars(select(Position).where(Position.user_id == user_id)).all())
    realized = round(sum(p.realized_pnl for p in positions), 2)
    open_positions = [p for p in positions if p.status == "open"]
    open_execution_ids = {p.strategy_execution_id for p in open_positions if p.strategy_execution_id}

    # Whole-strategy context: every OPEN execution with its full entry-order set.
    executions = list(
        db.scalars(
            select(StrategyExecution)
            .where(StrategyExecution.user_id == user_id)
            .order_by(StrategyExecution.entry_at.desc())
        ).all()
    )
    all_orders = list(
        db.scalars(
            select(PaperOrder).where(
                PaperOrder.user_id == user_id,
                PaperOrder.kind == "entry",
                PaperOrder.status == "FILLED",
            )
        ).all()
    )

    strategies = []
    outlays = []
    estimates = []
    for ex in executions:
        if ex.execution_id not in open_execution_ids:
            continue  # closed strategy no longer engages capital
        ex_orders = [o for o in all_orders if o.execution_id == ex.execution_id]
        outlay = premium_outlay_for_orders(ex_orders)
        estimate = estimate_capital_for_execution(ex.entry_net)
        outlays.append(outlay)
        estimates.append(estimate)
        strategies.append(
            {
                "execution_id": ex.execution_id,
                "strategy_tag": ex.strategy_tag,
                "symbol": ex.symbol,
                "entry_net": round(ex.entry_net, 2),
                "premium_outlay": outlay,
                "estimated_capital": estimate["value"],
                "estimated_capital_basis": estimate["basis"],
            }
        )

    premium_outlay = {
        "value": round(sum(outlays), 2),
        "source": SOURCE_CALCULATED,
        "status": STATUS_AVAILABLE,  # 0 is a valid outlay (nothing bought)
    }
    estimated = aggregate_estimates(estimates)
    capital_used_value = estimated["value"] if is_valid_number(estimated["value"]) else None

    # Broker snapshot (async boundary for a future real provider; today it is
    # the unavailable provider — never a fabricated margin number).
    snapshot = await provider.get_capital_snapshot(
        {
            "user_id": user_id,
            "broker": "upstox",
            "strategies": strategies,
            "account": {
                "paper_starting_capital": starting,
                "paper_available_cash": available_cash,
            },
        }
    )
    broker_margin = capital_value(snapshot.get("broker_margin"), snapshot.get("source", SOURCE_BROKER_REPORTED))
    broker_margin["timestamp"] = snapshot.get("timestamp")
    broker_available_funds = capital_value(
        snapshot.get("broker_available_funds"), snapshot.get("source", SOURCE_BROKER_REPORTED)
    )
    broker_available_funds["timestamp"] = snapshot.get("timestamp")

    # Overall capital status reflects the capital-REQUIREMENT figures only
    # (broker margin + estimated capital), per §12.
    if broker_margin["status"] == STATUS_AVAILABLE and estimated["status"] == STATUS_AVAILABLE:
        overall_status = STATUS_AVAILABLE
    elif broker_margin["status"] == STATUS_UNAVAILABLE and estimated["status"] == STATUS_UNAVAILABLE:
        overall_status = STATUS_UNAVAILABLE
    else:
        overall_status = STATUS_PARTIAL

    return {
        "premium_outlay": premium_outlay,
        "broker_margin": broker_margin,
        "estimated_capital": estimated,
        # Phase 6.0 supports exactly one estimated-capital basis: premium.
        # When any estimate is present the aggregate carries that basis;
        # otherwise there is no basis to label.
        "estimated_capital_basis": BASIS_PREMIUM if estimated["status"] != STATUS_UNAVAILABLE else None,
        "broker_available_funds": broker_available_funds,
        "paper_starting_capital": capital_value(starting, SOURCE_CALCULATED),
        "paper_available_cash": capital_value(available_cash, SOURCE_CALCULATED),
        "capital_used": capital_value(capital_used_value, SOURCE_ESTIMATED),
        "remaining_capital": capital_value(available_cash, SOURCE_CALCULATED),
        "roc_inputs": capital_efficiency_inputs(realized, None, capital_used_value),
        "strategies": strategies,
        "generated_at": _now().isoformat(),
        "status": overall_status,
    }
