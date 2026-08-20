"""Phase 6.8C: Strategy Template Resolution Service.

Resolves strategy template legs (from DB or inline requests) against live
broker chain data. This service is the bridge between:

  stored formula (6.8B) -> pure resolver (6.8A) -> live chain -> resolved leg

CRITICAL: Resolution NEVER creates execution records. It is a read-only
preview/resolve operation. Execution is a separate step via /paper/executions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.brokers.domain.enums import BROKER_ID_UPSTOX
from app.brokers.domain.errors import BrokerError
from app.brokers.gateway import gateway
from app.services.strategy_resolver import (
    ExpiryMode,
    LegFormula,
    ResolverResult,
    StrikeMode,
    _resolve_expiry,
    _resolve_strike,
    chain_rows,
    resolve_leg,
    sorted_strikes,
    spot_price,
)


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------

@dataclass
class ResolvedLegOutput:
    """One fully resolved, executable leg."""

    # From the formula / template
    position: int
    action: str
    option_type: str
    quantity: int
    lot_size: int

    # Resolved values
    resolved_strike: float
    resolved_expiry: str  # YYYY-MM-DD

    # Diagnostic
    strike_mode_used: str
    expiry_mode_used: str
    anchor_value: float | None = None
    delta_actual: float | None = None

    # Live market data
    current_price: float | None = None
    price_status: str = "unavailable"  # available | stale | unavailable
    quote_timestamp: str | None = None
    ltp: float | None = None

    # Feedback
    warnings: list[str] = field(default_factory=list)

    # ExecutionLegIn-compatible fields for seamless handoff
    symbol: str = ""
    expiration_date: str = ""
    strike_price: float = 0.0


@dataclass
class ResolutionResult:
    """Aggregated resolution result for all legs."""

    status: str  # RESOLVED | RESOLVED_WITH_WARNINGS | PARTIAL | NO_PRICES | FAILED
    symbol: str
    legs: list[ResolvedLegOutput] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    template_id: int | None = None
    template_name: str | None = None


# ---------------------------------------------------------------------------
# Chain fetching (per expiry)
# ---------------------------------------------------------------------------

async def fetch_chain_for_expiry(
    access_token: str,
    symbol: str,
    expiry_date: str,
) -> dict | None:
    """Fetch the canonical transformed chain for one (symbol, expiry).

    Returns the canonical chain dict or None on broker error.
    """
    from app.brokers.adapters.upstox.mapper import transform_chain

    try:
        adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
        raw = await adapter.get_option_chain(symbol, expiry_date)
        # get_option_chain returns the canonical transformed chain already
        return raw
    except (BrokerError, Exception):
        return None


async def fetch_available_expiries(
    access_token: str,
    symbol: str,
) -> list[str]:
    """Fetch the list of listed expiry dates for a symbol."""
    from app.brokers.adapters.upstox.mapper import broker_key_for

    try:
        adapter = gateway.create(BROKER_ID_UPSTOX, access_token=access_token)
        instrument_key = broker_key_for(symbol)
        result = await adapter.get_option_contracts(symbol)
        expiries = result.get("expiries", [])
        return sorted(expiries)
    except (BrokerError, Exception):
        return []


# ---------------------------------------------------------------------------
# Price resolution from chain
# ---------------------------------------------------------------------------

def get_price_from_chain(
    chain_data: dict,
    strike: float,
    option_type: str,
) -> tuple[float | None, str | None, str]:
    """Extract LTP and quote timestamp from canonical chain data.

    Returns (ltp, quote_timestamp, price_status).
    """
    chain_rows = chain_data.get("chain", [])
    for row in chain_rows:
        if abs(row["strike"] - strike) < 0.001:
            side = row.get(option_type) or {}
            ltp = side.get("ltp")
            quote_ts = side.get("quote_timestamp")
            if ltp is not None and ltp > 0:
                return ltp, quote_ts, "available"
            return None, None, "unavailable"
    return None, None, "unavailable"


def is_stale_quote(quote_timestamp: str | None, max_age_seconds: int = 300) -> bool:
    """Check if a quote is stale (> max_age_seconds old).

    Returns True if stale or if timestamp is missing/invalid.
    """
    if not quote_timestamp:
        return False  # No timestamp = we can't determine staleness

    try:
        from datetime import datetime, timezone
        # Parse ISO format timestamp
        ts = datetime.fromisoformat(quote_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = (now - ts).total_seconds()
        return age > max_age_seconds
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Leg formula builder
# ---------------------------------------------------------------------------

def build_leg_formula(leg_data: dict) -> LegFormula:
    """Convert a leg dict (from template or inline) to a LegFormula for the resolver."""

    strike_mode_str = leg_data.get("strike_mode", "fixed")
    expiry_mode_str = leg_data.get("expiry_mode", "fixed")

    try:
        strike_mode = StrikeMode(strike_mode_str)
    except ValueError:
        strike_mode = StrikeMode.FIXED

    try:
        expiry_mode = ExpiryMode(expiry_mode_str)
    except ValueError:
        expiry_mode = ExpiryMode.FIXED

    return LegFormula(
        action=leg_data["action"],
        option_type=leg_data["option_type"],
        quantity=leg_data.get("quantity", 1),
        lot_size=leg_data.get("lot_size", 50),
        strike_mode=strike_mode,
        strike=leg_data.get("strike"),
        strike_offset=leg_data.get("strike_offset"),
        strike_offset_steps=leg_data.get("strike_offset"),
        target_delta=leg_data.get("target_delta"),
        expiry_mode=expiry_mode,
        expiry=leg_data.get("expiry"),
        expiry_dte_min=leg_data.get("expiry_dte_min"),
        expiry_dte_max=leg_data.get("expiry_dte_max"),
    )


# ---------------------------------------------------------------------------
# Core resolution engine
# ---------------------------------------------------------------------------

async def resolve_legs(
    access_token: str,
    symbol: str,
    legs: list[dict],
    template_id: int | None = None,
    template_name: str | None = None,
) -> ResolutionResult:
    """Resolve a list of legs against live broker chain data.

    This is the core resolution engine. It:
    1. Groups legs by their resolved expiry (for fixed expiry) or collects all expiries
    2. Fetches the chain for each unique expiry
    3. Resolves each leg using the 6.8A resolver
    4. Extracts live prices from the resolved chain
    5. Returns fully resolved legs with market data

    CRITICAL: This NEVER creates execution records. It is read-only.
    """
    if not legs:
        return ResolutionResult(
            status="FAILED",
            symbol=symbol,
            errors=["No legs provided."],
            template_id=template_id,
            template_name=template_name,
        )

    # Step 1: Determine which expiries we need to fetch
    # For fixed expiry legs, we know the exact expiry
    # For dynamic expiry modes, we need to fetch all expiries first
    fixed_expiries: set[str] = set()
    has_dynamic_expiry = False

    for leg in legs:
        expiry_mode = leg.get("expiry_mode", "fixed")
        if expiry_mode == "fixed":
            fixed_expiries.add(leg["expiry"])
        else:
            has_dynamic_expiry = True

    # Step 2: Fetch broker-provided expiry list and validate fixed expiries
    all_expiries: list[str] = []
    chains: dict[str, dict] = {}  # expiry -> chain data
    pre_check_errors: list[str] = []

    if has_dynamic_expiry or not fixed_expiries:
        all_expiries = await fetch_available_expiries(access_token, symbol)
    else:
        # Fetch the broker expiry list even for fixed legs so we can
        # validate that every requested fixed expiry actually exists.
        broker_expiries = await fetch_available_expiries(access_token, symbol)
        if broker_expiries:
            all_expiries = broker_expiries
            # Validate each fixed expiry against the broker list
            for fe in fixed_expiries:
                if fe not in broker_expiries:
                    pre_check_errors.append(
                        f"EXPIRY_UNAVAILABLE: {fe} is not in the broker-provided "
                        f"expiry list for {symbol}. "
                        f"Available: {', '.join(sorted(broker_expiries))}"
                    )
        else:
            # Broker expiry list unavailable — fall back to fixed set
            all_expiries = sorted(fixed_expiries)

    if pre_check_errors:
        return ResolutionResult(
            status="FAILED",
            symbol=symbol,
            errors=pre_check_errors,
            template_id=template_id,
            template_name=template_name,
        )

    # Fetch chains for each needed expiry
    for expiry in all_expiries:
        chain = await fetch_chain_for_expiry(access_token, symbol, expiry)
        if chain is not None:
            chains[expiry] = chain

    if not chains:
        return ResolutionResult(
            status="NO_PRICES",
            symbol=symbol,
            errors=[f"Could not fetch chain data for {symbol}. No expiries available."],
            template_id=template_id,
            template_name=template_name,
        )

    # Step 3: Resolve each leg
    resolved_legs: list[ResolvedLegOutput] = []
    all_warnings: list[str] = []
    all_errors: list[str] = []

    for i, leg_data in enumerate(legs):
        position = leg_data.get("position", i)
        formula = build_leg_formula(leg_data)

        # For fixed expiry, resolve against the specific chain
        # For dynamic expiry, try each available chain
        leg_resolved = False

        if formula.expiry_mode == ExpiryMode.FIXED and formula.expiry in chains:
            result = resolve_leg(formula, chains[formula.expiry], all_expiries, date.today())
            if result.ok:
                resolved = result.leg
                ltp, quote_ts, price_status = get_price_from_chain(
                    chains[formula.expiry], resolved.resolved_strike, formula.option_type
                )
                if price_status == "available" and is_stale_quote(quote_ts):
                    price_status = "stale"

                resolved_legs.append(ResolvedLegOutput(
                    position=position,
                    action=formula.action,
                    option_type=formula.option_type,
                    quantity=formula.quantity,
                    lot_size=formula.lot_size,
                    resolved_strike=resolved.resolved_strike,
                    resolved_expiry=resolved.resolved_expiry,
                    strike_mode_used=resolved.strike_mode_used,
                    expiry_mode_used=resolved.expiry_mode_used,
                    anchor_value=resolved.anchor_value,
                    delta_actual=resolved.delta_actual,
                    current_price=ltp,
                    price_status=price_status,
                    quote_timestamp=quote_ts,
                    ltp=ltp,
                    warnings=resolved.warnings,
                    symbol=symbol,
                    expiration_date=resolved.resolved_expiry,
                    strike_price=resolved.resolved_strike,
                ))
                all_warnings.extend(resolved.warnings)
                leg_resolved = True
            else:
                all_errors.extend(result.errors)
        elif formula.expiry_mode != ExpiryMode.FIXED:
            # Phase 6.8D fix: resolve expiry FIRST, then resolve strike
            # and extract price from THAT expiry's chain.
            try:
                resolved_expiry, expiry_warnings = _resolve_expiry(
                    formula, all_expiries, date.today(),
                )
            except ValueError as exc:
                all_errors.append(str(exc))
                leg_resolved = False
            else:
                all_warnings.extend(expiry_warnings)
                # Now use exactly the resolved expiry's chain
                if resolved_expiry in chains:
                    chain_for_expiry = chains[resolved_expiry]
                    result = resolve_leg(formula, chain_for_expiry, all_expiries, date.today())
                    if result.ok:
                        resolved = result.leg
                        # Price extracted from the RESOLVED expiry's chain
                        ltp, quote_ts, price_status = get_price_from_chain(
                            chain_for_expiry, resolved.resolved_strike, formula.option_type,
                        )
                        if price_status == "available" and is_stale_quote(quote_ts):
                            price_status = "stale"

                        resolved_legs.append(ResolvedLegOutput(
                            position=position,
                            action=formula.action,
                            option_type=formula.option_type,
                            quantity=formula.quantity,
                            lot_size=formula.lot_size,
                            resolved_strike=resolved.resolved_strike,
                            resolved_expiry=resolved.resolved_expiry,
                            strike_mode_used=resolved.strike_mode_used,
                            expiry_mode_used=resolved.expiry_mode_used,
                            anchor_value=resolved.anchor_value,
                            delta_actual=resolved.delta_actual,
                            current_price=ltp,
                            price_status=price_status,
                            quote_timestamp=quote_ts,
                            ltp=ltp,
                            warnings=resolved.warnings,
                            symbol=symbol,
                            expiration_date=resolved.resolved_expiry,
                            strike_price=resolved.resolved_strike,
                        ))
                        all_warnings.extend(resolved.warnings)
                        leg_resolved = True
                    else:
                        all_errors.extend(result.errors)
                else:
                    all_errors.append(
                        f"Chain data for resolved expiry {resolved_expiry} is not available."
                    )

        if not leg_resolved:
            all_errors.append(f"Leg {i} ({formula.action} {formula.option_type}) could not be resolved.")

    # Step 4: Determine overall status
    if all_errors:
        status = "FAILED"
    elif all_warnings:
        status = "RESOLVED_WITH_WARNINGS"
    else:
        status = "RESOLVED"

    # Check if any legs have unavailable prices
    has_unavailable = any(leg.price_status == "unavailable" for leg in resolved_legs)
    if has_unavailable and status == "RESOLVED":
        status = "NO_PRICES"
    elif has_unavailable and status == "RESOLVED_WITH_WARNINGS":
        status = "PARTIAL"

    return ResolutionResult(
        status=status,
        symbol=symbol,
        legs=resolved_legs,
        errors=all_errors,
        warnings=all_warnings,
        template_id=template_id,
        template_name=template_name,
    )
