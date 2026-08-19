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

Data quality levels:
- ``available``: LTP resolved from broker; quote_timestamp within
  STALE_THRESHOLD_SECONDS of current time (or timestamp unavailable).
- ``stale``: LTP resolved but quote_timestamp is older than
  STALE_THRESHOLD_SECONDS — price may be outdated.
- ``unavailable``: LTP not resolved (missing from chain, broker error,
  or chain fetch failed).

Per-leg entry price:
- Each StrategyLegExposure references a source PaperOrder via ``order_id``.
- The leg's authoritative entry price is ``PaperOrder.fill_price``.
- When the source order cannot be joined (missing, not FILLED, etc.),
  leg-level P&L is returned as ``None`` / unavailable — never fabricated
  from the position's average entry price.

P&L percentage (position-level):
- Live P&L % = Live P&L / Entry Value × 100
- Entry Value = Average Entry Price × abs(net_quantity) × lot_size
- This is NOT Live P&L / Market Value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaperOrder, Position, StrategyExecution, StrategyLegExposure
from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.gateway import gateway
from app.services.paper_execution import unrealized_pnl

# ---------------------------------------------------------------------------
# Stale-price threshold
# ---------------------------------------------------------------------------
# Quotes whose ``quote_timestamp`` is older than this are classified as
# ``stale`` rather than ``available``.  The threshold is deliberately
# conservative: option premiums can move quickly, but intra-minute noise
# does not make a quote stale.
STALE_THRESHOLD_SECONDS: int = 300  # 5 minutes


def _is_stale(quote_timestamp: str | None, now: datetime) -> bool:
    """Return True when the quote is older than STALE_THRESHOLD_SECONDS.

    If no timestamp is provided, returns False (we cannot determine
    staleness — treat as ``available`` rather than ``stale``).
    """
    if not quote_timestamp:
        return False
    try:
        qt = datetime.fromisoformat(quote_timestamp)
        # Ensure timezone-aware for comparison
        if qt.tzinfo is None:
            qt = qt.replace(tzinfo=timezone.utc)
        return (now - qt) > timedelta(seconds=STALE_THRESHOLD_SECONDS)
    except (ValueError, TypeError):
        return False


@dataclass
class LegValuation:
    """One StrategyLegExposure's live valuation."""

    exposure_id: int
    execution_id: str
    action: str  # buy | sell
    remaining_quantity: int  # lots
    lot_size: int
    entry_price: float | None = None  # authoritative per-leg entry (PaperOrder.fill_price)
    current_price: float | None = None
    market_value: float | None = None  # LTP × remaining_qty × lot_size
    live_pnl: float | None = None
    price_status: str = "unavailable"  # available | stale | unavailable


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
    live_pnl: float | None = None
    # Live P&L % = live_pnl / entry_value × 100
    # where entry_value = average_entry_price × abs(net_quantity) × lot_size
    live_pnl_pct: float | None = None
    price_status: str = "unavailable"  # available | stale | unavailable
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
    entry_price: float,
    lot_size: int,
) -> float | None:
    """Compute live P&L for a single strategy leg.

    Uses the per-leg entry price (from the source PaperOrder.fill_price),
    NOT the position-level average entry price.

    A BUY leg is long (+), a SELL leg is short (−).
    """
    if remaining_quantity <= 0:
        return None
    # Build a synthetic net_quantity: buy = +qty, sell = -qty
    signed_qty = remaining_quantity if action == "buy" else -remaining_quantity
    return unrealized_pnl(signed_qty, entry_price, current_price, lot_size)


def _resolve_entry_prices(
    db: Session,
    user_id: str,
    exposure_rows: list[StrategyLegExposure],
) -> dict[int, float | None]:
    """Resolve authoritative entry price for each StrategyLegExposure.

    Joins StrategyLegExposure.order_id → PaperOrder.fill_price.
    Returns {exposure_id: fill_price | None}.

    Only FILLED orders with a non-null fill_price are considered
    authoritative. All others return None (caller treats as unavailable).
    """
    order_ids = list({exp.order_id for exp in exposure_rows if exp.order_id})
    if not order_ids:
        return {}

    orders = list(
        db.scalars(
            select(PaperOrder).where(
                PaperOrder.user_id == user_id,
                PaperOrder.id.in_(order_ids),
            )
        ).all()
    )
    # Build order_id → fill_price for FILLED orders only.
    price_map: dict[int, float | None] = {}
    for o in orders:
        if o.status == "FILLED" and o.fill_price is not None:
            price_map[o.id] = o.fill_price
        else:
            price_map[o.id] = None

    return {exp.id: price_map.get(exp.order_id) for exp in exposure_rows}


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
    4. Aggregate strategy-level and leg-level P&L from StrategyLegExposure
       using authoritative per-leg entry prices (PaperOrder.fill_price).

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

    # Resolve LTP + quote_timestamp via the existing broker adapter.
    adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
    # (sym, exp, strike, type) → (LTP, quote_timestamp | None)
    price_data: dict[tuple[str, str, float, str], tuple[float | None, str | None]] = {}
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
                    qts = side.get("quote_timestamp") if side else None
                    key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
                    price_data[key] = (ltp if ltp is not None and ltp > 0 else None, qts)
                    if ltp is None or ltp <= 0:
                        chain_errors.append(
                            f"{p.symbol} {p.strike:g} {p.option_type.upper()} ({p.expiry})"
                        )
            except Exception as exc:
                for p in pos_list:
                    key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
                    price_data[key] = (None, None)
                chain_errors.append(f"Chain fetch failed for {symbol} {expiry}: {exc}")
    except Exception:
        for p in positions:
            key = (p.symbol.upper(), p.expiry, p.strike, p.option_type)
            price_data[key] = (None, None)
        chain_errors.append("Broker unavailable — all market data unavailable")

    # Fetch strategy tags in batch.
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

    # Fetch leg exposures in batch.
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

    # Resolve authoritative per-leg entry prices via PaperOrder.fill_price.
    leg_entry_prices = _resolve_entry_prices(db, user_id, exposure_rows)

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
        ltp, qts = price_data.get(key, (None, None))
        side = "LONG" if p.net_quantity > 0 else "SHORT" if p.net_quantity < 0 else "CLOSED"

        # Determine position-level price_status including staleness.
        if ltp is None or ltp <= 0:
            price_status = "unavailable"
        elif _is_stale(qts, now):
            price_status = "stale"
        else:
            price_status = "available"

        has_ltp = ltp is not None and ltp > 0
        mv = None
        pnl = None
        pnl_pct = None

        if has_ltp:
            pnl, mv = compute_position_pnl(
                p.net_quantity, p.average_entry_price, ltp, p.lot_size
            )
            # P&L %: live_pnl / entry_value × 100
            # entry_value = average_entry_price × abs(net_quantity) × lot_size
            entry_value = abs(p.average_entry_price * p.net_quantity * p.lot_size)
            if entry_value > 0:
                pnl_pct = round(pnl / entry_value * 100, 2)
            has_any_price = True
            with_price += 1
        else:
            has_any_unavailable = True
            without_price += 1

        total_realized += p.realized_pnl

        # Strategy-level aggregation with per-leg entry prices.
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

            # Leg P&L: use the authoritative per-leg entry price from
            # PaperOrder.fill_price, NOT the position average entry.
            leg_entry = leg_entry_prices.get(leg.id)
            leg_pnl = None
            leg_mv = None
            leg_price_status = "unavailable"
            if has_ltp and leg_entry is not None:
                leg_pnl = compute_leg_pnl(
                    leg.action, leg.remaining_quantity, ltp,
                    leg_entry, p.lot_size,
                )
                leg_mv = round(ltp * leg.remaining_quantity * p.lot_size, 2)
                leg_price_status = "stale" if _is_stale(qts, now) else "available"

            lv = LegValuation(
                exposure_id=leg.id,
                execution_id=leg.execution_id,
                action=leg.action,
                remaining_quantity=leg.remaining_quantity,
                lot_size=p.lot_size,
                entry_price=leg_entry,
                current_price=ltp if has_ltp else None,
                market_value=leg_mv,
                live_pnl=leg_pnl,
                price_status=leg_price_status,
            )
            sv.legs.append(lv)

        # Aggregate strategy P&L from legs.
        for sv in strat_map.values():
            strat_pnl = 0.0
            strat_mv = 0.0
            leg_statuses = [lv.price_status for lv in sv.legs]
            for lv in sv.legs:
                if lv.live_pnl is not None:
                    strat_pnl += lv.live_pnl
                if lv.market_value is not None:
                    strat_mv += lv.market_value
            # Strategy status: available only if ALL legs are available.
            # stale if ANY leg is stale and none is unavailable.
            # unavailable if ANY leg is unavailable.
            if all(s == "available" for s in leg_statuses) and sv.legs:
                sv.price_status = "available"
            elif any(s == "unavailable" for s in leg_statuses):
                sv.price_status = "unavailable"
            elif any(s == "stale" for s in leg_statuses):
                sv.price_status = "stale"
            else:
                sv.price_status = "unavailable"
            sv.live_pnl = round(strat_pnl, 2) if any(lv.live_pnl is not None for lv in sv.legs) else None
            sv.market_value = round(strat_mv, 2) if any(lv.market_value is not None for lv in sv.legs) else None

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
            current_price=ltp if has_ltp else None,
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
