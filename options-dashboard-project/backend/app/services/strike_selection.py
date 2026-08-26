"""Historical strike/expiry selection — Phase 7.17.

Determines the historical ATM strike and selects the appropriate strike
universe for option-chain reconstruction.

**Critical requirement:** ATM is calculated from the historical NIFTY
index price corresponding to the historical trading period being
backfilled.  We NEVER use the current NIFTY price.

Architecture:
  1. Retrieve the historical NIFTY closing price from stored nifty_candles
  2. Round to the nearest strike interval (25 points for NIFTY)
  3. Select ATM ± 20 strikes (41 strikes total)
  4. Pair each strike with CE and PE (82 contracts total)
  5. Resolve each contract through contract_specs for authoritative metadata

**Lot-size independence:** This module does NOT use lot_size for strike
selection.  Lot_size is preserved in contract_specs and consumed only
by future GEX/exposure calculations.

**Monthly expiry selection:**
  - Query contract_specs for distinct monthly expiry dates
  - Filter to the requested historical window
  - Verify each expiry has contracts available
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.models import ContractSpec, NiftyCandle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# NIFTY strike interval (25 points)
NIFTY_STRIKE_INTERVAL = 25

# Default strike range: ATM ± 20 (41 strikes)
DEFAULT_STRIKE_RANGE = 20

# NSE trading hours (IST) for ATM reference candle selection
MARKET_OPEN_HOUR_IST = 9
MARKET_OPEN_MINUTE_IST = 15


# ---------------------------------------------------------------------------
# Historical ATM calculation
# ---------------------------------------------------------------------------

def get_historical_atm(
    db: Session,
    target_date: date | str,
    symbol: str = "NIFTY",
    interval: str = "3min",
) -> float | None:
    """Calculate the historical ATM strike for a given date.

    Uses the NIFTY closing price from the first available candle on the
    target date.  The price is rounded to the nearest NIFTY strike
    interval (25 points).

    Parameters
    ----------
    db : Session
        Database session with access to nifty_candles.
    target_date : date | str
        The historical date for which to determine ATM.
    symbol : str
        Index symbol (default "NIFTY").
    interval : str
        Candle interval (default "3min").

    Returns
    -------
    float or None
        The ATM strike price (rounded to nearest 25), or None if no
        index candles are available for that date.

    Notes
    -----
    - Uses the closing price of the first candle on the target date
      (typically 09:15 IST open candle).
    - If no candles exist for the exact date, tries the nearest prior
      trading day (up to 5 days back).
    - ATM is rounded to the nearest 25-point interval, following the
      NIFTY strike spacing convention.
    - NEVER uses the current NIFTY price.  This is the single most
      important invariant.
    """
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    # Try the target date first, then look back up to 5 days
    for offset in range(6):
        search_date = target_date - timedelta(days=offset)
        atm = _get_atm_from_candles(db, search_date, symbol, interval)
        if atm is not None:
            return atm

    return None


def _get_atm_from_candles(
    db: Session,
    target_date: date,
    symbol: str,
    interval: str,
) -> float | None:
    """Get ATM from stored NIFTY candles for a specific date."""
    # Convert date to UTC datetime range
    # We look for candles on the target date in IST timezone
    # IST = UTC+5:30, so 00:00 IST = 18:30 UTC previous day
    ist_offset = timedelta(hours=5, minutes=30)

    # Start of trading day in IST: 09:15 IST
    day_start_ist = datetime(
        target_date.year, target_date.month, target_date.day,
        MARKET_OPEN_HOUR_IST, MARKET_OPEN_MINUTE_IST,
        tzinfo=timezone(ist_offset),
    )
    # End of trading day in IST: 15:27 IST (NIFTY index close)
    day_end_ist = datetime(
        target_date.year, target_date.month, target_date.day,
        15, 27,
        tzinfo=timezone(ist_offset),
    )

    # Convert to UTC
    day_start_utc = day_start_ist.astimezone(timezone.utc)
    day_end_utc = day_end_ist.astimezone(timezone.utc)

    # Query the first candle on this trading day (opening candle)
    stmt = (
        select(NiftyCandle)
        .where(NiftyCandle.symbol == symbol.upper())
        .where(NiftyCandle.interval == interval)
        .where(NiftyCandle.open_time >= day_start_utc)
        .where(NiftyCandle.open_time <= day_end_utc)
        .order_by(NiftyCandle.open_time.asc())
        .limit(1)
    )
    row = db.scalars(stmt).first()

    if row is None:
        return None

    # Use the open price of the first candle as the ATM reference
    # This represents the NIFTY level at the start of the trading day
    reference_price = row.open

    if reference_price is None or reference_price <= 0:
        return None

    # Round to nearest strike interval
    return round_to_nearest_strike(reference_price)


def round_to_nearest_strike(
    price: float,
    interval: float = NIFTY_STRIKE_INTERVAL,
) -> float:
    """Round a price to the nearest strike interval.

    Parameters
    ----------
    price : float
        The underlying price (e.g., NIFTY closing price).
    interval : float
        Strike interval (default 25 for NIFTY).

    Returns
    -------
    float
        The nearest strike price.

    Examples
    --------
    >>> round_to_nearest_strike(24523)
    24525
    >>> round_to_nearest_strike(24512)
    24500
    >>> round_to_nearest_strike(24500)
    24500
    """
    return round(price / interval) * interval


# ---------------------------------------------------------------------------
# Strike universe selection
# ---------------------------------------------------------------------------

def select_strike_universe(
    atm: float,
    range_size: int = DEFAULT_STRIKE_RANGE,
    interval: float = NIFTY_STRIKE_INTERVAL,
) -> list[float]:
    """Select the strike universe around ATM.

    Parameters
    ----------
    atm : float
        The ATM strike price (must already be rounded to interval).
    range_size : int
        Number of strikes on each side of ATM (default 20).
    interval : float
        Strike interval (default 25 for NIFTY).

    Returns
    -------
    list[float]
        Sorted list of strikes from ATM - range_size*interval to
        ATM + range_size*interval.

    Examples
    --------
    >>> select_strike_universe(24500, range_size=2)
    [24450, 24475, 24500, 24525, 24550]
    """
    strikes = []
    for i in range(-range_size, range_size + 1):
        strike = atm + i * interval
        strikes.append(strike)
    return sorted(strikes)


def select_contract_universe(
    strikes: list[float],
    expiry: str,
    contract_specs: list[dict],
) -> list[dict]:
    """Select the contract universe for a given expiry and strike list.

    Parameters
    ----------
    strikes : list[float]
        List of strike prices.
    expiry : str
        Expiry date string (YYYY-MM-DD).
    contract_specs : list[dict]
        List of contract specification dicts from contract_specs table.

    Returns
    -------
    list[dict]
        List of matching contract specs with CE and PE for each strike.

    Notes
    -----
    - Only returns contracts that exist in contract_specs
    - Preserves instrument_key, lot_size, and all metadata
    - Logs warnings for missing contracts (strike exists but no contract)
    """
    # Index contracts by (strike, type) for fast lookup
    contract_map: dict[tuple[float, str], dict] = {}
    for spec in contract_specs:
        if spec.get("expiry") != expiry:
            continue
        strike = spec.get("strike_price")
        ctype = spec.get("instrument_type", "").upper()
        if strike is not None and ctype in ("CE", "PE"):
            contract_map[(strike, ctype)] = spec

    result = []
    missing = []

    for strike in strikes:
        for ctype in ("CE", "PE"):
            key = (strike, ctype)
            if key in contract_map:
                result.append(contract_map[key])
            else:
                missing.append(f"{strike} {ctype}")

    if missing:
        logger.warning(
            "Missing %d contracts for expiry %s: %s",
            len(missing), expiry, ", ".join(missing[:10]),
        )

    return result


# ---------------------------------------------------------------------------
# Monthly expiry selection
# ---------------------------------------------------------------------------

def select_monthly_expiries(
    db: Session,
    start_date: date | str,
    end_date: date | str,
    underlying: str = "NIFTY",
) -> list[str]:
    """Select monthly expiry dates within a date range.

    Parameters
    ----------
    db : Session
        Database session with access to contract_specs.
    start_date : date | str
        Start of the date range (inclusive).
    end_date : date | str
        End of the date range (inclusive).
    underlying : str
        Underlying symbol (default "NIFTY").

    Returns
    -------
    list[str]
        Sorted list of expiry date strings (YYYY-MM-DD) that are
        monthly expiries within the range.

    Notes
    -----
    - Monthly expiries are identified as the last Thursday of each month
      (standard NSE expiry convention).
    - If no monthly expiry exists for a month, the available expiry
      closest to month-end is used.
    - Only returns expiries that have contracts in contract_specs.
    """
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    # Get all available expiry dates from contract_specs
    stmt = (
        select(distinct(ContractSpec.expiry))
        .where(ContractSpec.underlying == underlying)
        .where(ContractSpec.expiry >= start_date.isoformat())
        .where(ContractSpec.expiry <= end_date.isoformat())
        .order_by(ContractSpec.expiry.asc())
    )
    all_expiries = [row[0] for row in db.execute(stmt).all()]

    if not all_expiries:
        return []

    # Group by year-month and select the latest expiry per month
    monthly: dict[str, str] = {}
    for exp_str in all_expiries:
        try:
            exp_date = date.fromisoformat(exp_str)
        except ValueError:
            continue
        year_month = f"{exp_date.year}-{exp_date.month:02d}"
        # Keep the latest expiry in each month
        if year_month not in monthly or exp_str > monthly[year_month]:
            monthly[year_month] = exp_str

    return sorted(monthly.values())


# ---------------------------------------------------------------------------
# Full selection pipeline
# ---------------------------------------------------------------------------

def select_tier1_universe(
    db: Session,
    start_date: date | str,
    end_date: date | str,
    underlying: str = "NIFTY",
    strike_range: int = DEFAULT_STRIKE_RANGE,
) -> dict:
    """Select the complete Tier 1 backfill universe.

    This is the main entry point for strike/expiry selection.  It
    determines the historical ATM for each monthly expiry and selects
    the appropriate strike universe.

    Parameters
    ----------
    db : Session
        Database session.
    start_date : date | str
        Start of the historical window.
    end_date : date | str
        End of the historical window.
    underlying : str
        Underlying symbol.
    strike_range : int
        Strikes on each side of ATM (default 20).

    Returns
    -------
    dict
        Selection report with expiries, strikes, contracts, and metadata.
    """
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    # 1. Select monthly expiries
    monthly_expiries = select_monthly_expiries(
        db, start_date, end_date, underlying,
    )

    result = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "underlying": underlying,
        "strike_range": strike_range,
        "monthly_expiries": [],
        "total_contracts": 0,
        "total_strikes": 0,
    }

    for expiry_str in monthly_expiries:
        expiry_date = date.fromisoformat(expiry_str)

        # 2. Calculate historical ATM for this expiry
        # Use the first trading day of the expiry week as the ATM reference
        atm = get_historical_atm(db, expiry_date, symbol=underlying)

        # Fallback: if no index candles, use median strike from this expiry's contracts
        if atm is None:
            logger.info(
                "No ATM for %s — using median strike fallback",
                expiry_str,
            )
            all_strikes_for_expiry = [
                s.strike_price for s in db.execute(
                    select(ContractSpec)
                    .where(ContractSpec.underlying == underlying)
                    .where(ContractSpec.expiry == expiry_str)
                    .where(ContractSpec.strike_price > 0)
                ).scalars().all()
            ]
            if not all_strikes_for_expiry:
                logger.warning("No contracts for %s — skipping", expiry_str)
                continue
            median_strike = sorted(all_strikes_for_expiry)[len(all_strikes_for_expiry) // 2]
            atm = round_to_nearest_strike(median_strike)

        # 3. Select strike universe
        strikes = select_strike_universe(atm, strike_range)

        # 4. Get contract specs for this expiry
        stmt = (
            select(ContractSpec)
            .where(ContractSpec.underlying == underlying)
            .where(ContractSpec.expiry == expiry_str)
        )
        expiry_specs = [
            {
                "instrument_key": s.instrument_key,
                "expiry": s.expiry,
                "strike_price": s.strike_price,
                "instrument_type": s.instrument_type,
                "lot_size": s.lot_size,
                "minimum_lot": s.minimum_lot,
                "trading_symbol": s.trading_symbol,
                "underlying": s.underlying,
            }
            for s in db.execute(stmt).scalars().all()
        ]

        # 5. Select contracts matching our strikes
        contracts = select_contract_universe(
            strikes, expiry_str, expiry_specs,
        )

        # 6. Collect unique lot sizes for this expiry
        lot_sizes = list(set(c.get("lot_size") for c in contracts if c.get("lot_size")))

        expiry_info = {
            "expiry": expiry_str,
            "atm": atm,
            "lowest_strike": min(strikes) if strikes else None,
            "highest_strike": max(strikes) if strikes else None,
            "strike_count": len(strikes),
            "ce_count": sum(1 for c in contracts if c.get("instrument_type") == "CE"),
            "pe_count": sum(1 for c in contracts if c.get("instrument_type") == "PE"),
            "total_contracts": len(contracts),
            "lot_sizes": sorted(lot_sizes),
            "contracts": contracts,
        }

        result["monthly_expiries"].append(expiry_info)
        result["total_contracts"] += len(contracts)
        result["total_strikes"] += len(strikes)

    return result


# ---------------------------------------------------------------------------
# Selection report formatting
# ---------------------------------------------------------------------------

def format_selection_report(selection: dict) -> str:
    """Format a selection report as a readable table.

    Returns a markdown-formatted table showing the selection results.
    """
    lines = [
        "# Tier 1 Strike/Expiry Selection Report",
        "",
        f"Period: {selection['start_date']} to {selection['end_date']}",
        f"Underlying: {selection['underlying']}",
        f"Strike range: ATM ± {selection['strike_range']}",
        "",
        "| Expiry | ATM | Lowest Strike | Highest Strike | CE | PE | Total | Lot Sizes |",
        "|--------|----:|--------------:|---------------:|---:|---:|------:|-----------|",
    ]

    for exp in selection["monthly_expiries"]:
        lot_sizes_str = ", ".join(str(ls) for ls in exp["lot_sizes"]) if exp["lot_sizes"] else "N/A"
        lines.append(
            f"| {exp['expiry']} | {exp['atm']:.0f} | "
            f"{exp['lowest_strike']:.0f} | {exp['highest_strike']:.0f} | "
            f"{exp['ce_count']} | {exp['pe_count']} | "
            f"{exp['total_contracts']} | {lot_sizes_str} |"
        )

    lines.extend([
        "",
        f"**Total contracts: {selection['total_contracts']}**",
        f"**Total unique strikes: {selection['total_strikes']}**",
        "",
    ])

    return "\n".join(lines)
