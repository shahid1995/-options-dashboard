"""Server-authoritative live position valuation (Phase 6.6.6).

Provides live/unrealized P&L for open positions by resolving current LTP
from the existing broker market-data infrastructure (option chain).

Architecture:
- Reuses the existing broker adapter's ``get_option_chain`` — no second
  independent pricing source.
- P&L calculations are server-authoritative; the frontend never computes.
- Missing/stale/unavailable LTP is explicit (``None``), never interpreted
  as zero.
- Strategy-level and leg-level aggregation is deterministic.
- Quantities are LOTS; rupee exposure scales by ``lot_size``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Position, StrategyExecution, StrategyLegExposure
from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.gateway import gateway
from app.services.paper_execution import unrealized_pnl


@dataclass
class LegValuation:
    """One StrategyLegExposure's live valuation."""

    exposure_id: int
    execution_id: str
    action: str  # buy | sell
    remaining_quantity: int  # lots
    lot_size: int
    current_price: float | None = None
    market_value: float | None = None  # LTP × remaining_qty × lot_size
    live_pnl: float | None = None
    price_status: str = "unavailable"  # available | unavailable


@dataclass
class StrategyValuation:
    """Aggregated live valuation for one strategy execution within a position."""

    execution_id: str | None = None
    strategy_tag: str = "Custom"
    live_pnl: float | None = None
    market_value: float | None = None
    legs: list[LegValuation] = field(default_factory=list)
    price_status: str = "unavailable"  # best status across legs


@dataclass
class PositionValuation:
    """One open position's complete live valuation."""

    position_id: int
    symbol: str
    expiry: str
    strike: float
    option_type: str
    side: str  # LONG | SHORT
    net_quantity: int  # signed lots
    average_entry_price: float
    lot_size: int
    realized_pnl: float
    # Live valuation
    current_price: float | None = None
    market_value: float | None = None  # LTP × |net_quantity| × lot_size
    live_pnl: float | None = None  # (LTP − avg_entry) × qty × lot_size (long)
    live_pnl_pct: float | None = None  # live_pnl / (avg_entry × qty × lot_size) × 100
    price_status: str = "unavailable"  # available | unavailable
    # Strategy aggregation
    strategies: list[StrategyValuation] = field(default_factory=list)


@dataclass
class ValuationSummary:
    """Aggregate portfolio valuation across all open positions."""

    total_live_pnl: float | None = None
    total_market_value: float | None = None
    total_realized_pnl: float = 0.0
    open_position_count: int = 0
    positions_with_price: int = 0
    positions_unavailable: int = 0
    generated_at: str = ""
    status: str = "available"  # available | partial | unavailable


def compute_position_pnl(
    net_quantity: int,
    average_entry_price: float,
    current_price: float,
    lot_size: int,
) -> tuple[float, float]:
    """Compute live P&L and market value for one position.

    Long:  P&L = (LTP − avg) × qty × lot
    Short: P&L = (avg − LTP) × qty × lot
    Market Value = LTP × |qty| × lot

    Returns (live_pnl, market_value).
    """
    contracts = abs(net_quantity) * lot_size
    market_value = round(current_price * contracts, 2)
    pnl = unrealized_pnl(net_quantity, average_entry_price, current_price, lot_size)
    return pnl, market_value


def compute_leg_pnl(
    action: str,
    remaining_quantity: int,
    current_price: float,
    avg_entry_price: float,
    lot_size: int,
) -> float | None:
    """Compute live P&L for a single strategy leg.

    A BUY leg is long (+), a SELL leg is short (−).
    """
    if remaining_quantity <= 0:
        return None
    # Build a synthetic net_quantity: buy = +qty, sell = -qty
    signed_qty = remaining_quantity if action == "buy" else -remaining_quantity
    return unrealized_pnl(signed_qty, avg_entry_price, current_price, lot_size)


async def resolve_live_valuation(
    db: Session,
    user_id: str,
    access_token: str,
    *,
    positions: list[Position] | None = None,
) -> tuple[list[PositionValuation], ValuationSummary]:
    """Resolve server-authoritative live valuation for a user's open positions.

    1. Fetch open positions (if not provided).
    2. Group by (symbol, expiry) and resolve LTP from the broker adapter.
    3. Compute per-position P&L, market value, P&L %.
    4. Aggregate strategy-level and leg-level P&L from StrategyLegExposure.

    Returns (position_valuations, summary).
    """
    now = datetime.now(timezone.utc)

    if positions is None:
        positions = list(
            db.scalars(
                select(Position).where(
                    Position.user_id == user_id,
                    Position.status == "open",
                    Position.net_quantity != 0,
                )
            ).all()
        )

    if not positions:
        return [], ValuationSummary(
            total_live_pnl=0.0,
            total_market_value=0.0,
            total_realized_pnl=0.0,
            open_position_count=0,
            positions_with_price=0,
            positions_unavailable=0,
            generated_at=now.isoformat(),
            status="available",
        )

    # Group positions by (symbol, expiry) for batched chain fetches.
    by_chain: dict[tuple[str, str], list[Position]] = {}
    for p in positions:
        by_chain.setdefault((p.symbol.upper(), p.expiry), []).append(p)

    # Resolve LTP via the existing broker adapter.
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
    ltp_map: dict[tuple[str, str, float, str], float | None] = {}  # (sym, exp, strike, type) → LTP
    chain_errors: list[str] = []

    try:
        for (symbol, expiry), pos_list in by_chain.items():
            try:
                chain_resp = await adapter.get_option_chain(symbol, expiry)
                chain = chain_resp.get("chain", [])
                by_strike = {row["strike"]: row for row in chain}
                for p in pos_list:
                    row = by_strike.get(p.strike)
                    side = row.get(p.option_type) if row else None
                    ltp = side.get("ltp") if side else None
                    key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
                    if ltp is not None and ltp > 0:
                        ltp_map[key] = ltp
                    else:
                        ltp_map[key] = None
                        chain_errors.append(
                            f"{p.symbol} {p.strike:g} {p.option_type.upper()} ({p.expiry})"
                        )
            except Exception as exc:
                # Mark all positions in this chain as unavailable.
                for p in pos_list:
                    key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
                    ltp_map[key] = None
                chain_errors.append(f"Chain fetch failed for {symbol} {expiry}: {exc}")
    except Exception:
        # Broker completely unavailable — all prices unavailable.
        for p in positions:
            key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
            ltp_map[key] = None
        chain_errors.append("Broker unavailable — all market data unavailable")

    # Fetch strategy tags and leg exposures in batch.
    exec_ids = {p.strategy_execution_id for p in positions if p.strategy_execution_id}
    tags: dict[str, str] = {}
    if exec_ids:
        rows = db.execute(
            select(StrategyExecution.execution_id, StrategyExecution.strategy_tag).where(
                StrategyExecution.user_id == user_id,
                StrategyExecution.execution_id.in_(exec_ids),
            )
        ).all()
        tags = {r[0]: r[1] or "Custom" for r in rows}

    position_ids = [p.id for p in positions]
    exposure_rows = list(
        db.scalars(
            select(StrategyLegExposure).where(
                StrategyLegExposure.user_id == user_id,
                StrategyLegExposure.position_id.in_(position_ids),
                StrategyLegExposure.status == "open",
                StrategyLegExposure.remaining_quantity > 0,
            ).order_by(StrategyLegExposure.id.asc())
        ).all()
    )
    exposures_by_pos: dict[int, list[StrategyLegExposure]] = {}
    for exp in exposure_rows:
        exposures_by_pos.setdefault(exp.position_id, []).append(exp)

    # Build per-position valuations.
    result: list[PositionValuation] = []
    total_live = 0.0
    total_mv = 0.0
    total_realized = 0.0
    with_price = 0
    without_price = 0
    has_any_price = False
    has_any_unavailable = False

    for p in positions:
        key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
        ltp = ltp_map.get(key)
        side = "LONG" if p.net_quantity > 0 else "SHORT" if p.net_quantity < 0 else "CLOSED"
        price_status = "available" if ltp is not None and ltp > 0 else "unavailable"

        mv = None
        pnl = None
        pnl_pct = None

        if ltp is not None and ltp > 0:
            pnl, mv = compute_position_pnl(
                p.net_quantity, p.average_entry_price, ltp, p.lot_size
            )
            # P&L %: P&L / (avg_entry × |qty| × lot_size) × 100
            invested = abs(p.average_entry_price * p.net_quantity * p.lot_size)
            if invested > 0:
                pnl_pct = round(pnl / invested * 100, 2)
            has_any_price = True
            with_price += 1
        else:
            has_any_unavailable = True
            without_price += 1

        total_realized += p.realized_pnl

        # Strategy-level aggregation.
        legs_for_pos = exposures_by_pos.get(p.id, [])
        strat_map: dict[str | None, StrategyValuation] = {}
        for leg in legs_for_pos:
            eid = leg.execution_id
            if eid not in strat_map:
                strat_map[eid] = StrategyValuation(
                    execution_id=eid,
                    strategy_tag=tags.get(eid, "Custom"),
                    legs=[],
                )
            sv = strat_map[eid]

            # Leg P&L: use the position's average entry as the leg entry price.
            # (The backend stores position-level avg entry; per-leg avg entry
            # is not tracked separately.)
            leg_pnl = None
            leg_mv = None
            leg_price_status = "unavailable"
            if ltp is not None and ltp > 0:
                leg_pnl = compute_leg_pnl(
                    leg.action, leg.remaining_quantity, ltp,
                    p.average_entry_price, p.lot_size,
                )
                leg_mv = round(ltp * leg.remaining_quantity * p.lot_size, 2)
                leg_price_status = "available"

            lv = LegValuation(
                exposure_id=leg.id,
                execution_id=leg.execution_id,
                action=leg.action,
                remaining_quantity=leg.remaining_quantity,
                lot_size=p.lot_size,
                current_price=ltp if ltp is not None and ltp > 0 else None,
                market_value=leg_mv,
                live_pnl=leg_pnl,
                price_status=leg_price_status,
            )
            sv.legs.append(lv)

        # Aggregate strategy P&L from legs.
        for sv in strat_map.values():
            strat_pnl = 0.0
            strat_mv = 0.0
            all_available = True
            for lv in sv.legs:
                if lv.live_pnl is not None:
                    strat_pnl += lv.live_pnl
                if lv.market_value is not None:
                    strat_mv += lv.market_value
                if lv.price_status != "available":
                    all_available = False
            sv.live_pnl = round(strat_pnl, 2) if any(lv.live_pnl is not None for lv in sv.legs) else None
            sv.market_value = round(strat_mv, 2) if any(lv.market_value is not None for lv in sv.legs) else None
            sv.price_status = "available" if all_available and sv.legs else ("unavailable" if not all_available else "unavailable")

        strategies = list(strat_map.values())

        if pnl is not None:
            total_live += pnl
        if mv is not None:
            total_mv += mv

        pv = PositionValuation(
            position_id=p.id,
            symbol=p.symbol,
            expiry=p.expiry,
            strike=p.strike,
            option_type=p.option_type,
            side=side,
            net_quantity=p.net_quantity,
            average_entry_price=p.average_entry_price,
            lot_size=p.lot_size,
            realized_pnl=p.realized_pnl,
            current_price=ltp if ltp is not None and ltp > 0 else None,
            market_value=mv,
            live_pnl=round(pnl, 2) if pnl is not None else None,
            live_pnl_pct=pnl_pct,
            price_status=price_status,
            strategies=strategies,
        )
        result.append(pv)

    # Determine overall status.
    if has_any_price and has_any_unavailable:
        status = "partial"
    elif has_any_price:
        status = "available"
    else:
        status = "unavailable"

    summary = ValuationSummary(
        total_live_pnl=round(total_live, 2) if has_any_price else None,
        total_market_value=round(total_mv, 2) if has_any_price else None,
        total_realized_pnl=round(total_realized, 2),
        open_position_count=len(positions),
        positions_with_price=with_price,
        positions_unavailable=without_price,
        generated_at=now.isoformat(),
        status=status,
    )

    return result, summary
