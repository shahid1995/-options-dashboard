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
    chain_strike_step: float | None = None  # min strike spacing from the chain


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

    # strike_offset is overloaded in the input dict: it carries rupee offset
    # for atm_offset/spot_offset modes AND step count for atm_offset_steps.
    # Route to the correct LegFormula field based on the resolved strike mode.
    raw_offset = leg_data.get("strike_offset")
    return LegFormula(
        action=leg_data["action"],
        option_type=leg_data["option_type"],
        quantity=leg_data.get("quantity", 1),
        lot_size=leg_data.get("lot_size", 50),
        strike_mode=strike_mode,
        strike=leg_data.get("strike"),
        strike_offset=raw_offset if strike_mode in (StrikeMode.ATM_OFFSET, StrikeMode.SPOT_OFFSET) else None,
        strike_offset_steps=int(raw_offset) if strike_mode == StrikeMode.ATM_OFFSET_STEPS and raw_offset is not None else None,
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

    # Compute chain strike step from the first available chain.
    # Defensive: filter non-numeric, deduplicate, only positive diffs.
    chain_strike_step = None
    for chain in chains.values():
        raw_strikes = []
        for r in chain.get("chain", []):
            s = r.get("strike")
            if isinstance(s, (int, float)) and s > 0:
                raw_strikes.append(s)
        strikes = sorted(set(raw_strikes))
        if len(strikes) >= 2:
            positive_diffs = [
                strikes[i + 1] - strikes[i]
                for i in range(len(strikes) - 1)
                if strikes[i + 1] > strikes[i]
            ]
            chain_strike_step = min(positive_diffs) if positive_diffs else None
            break

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
        chain_strike_step=chain_strike_step,
    )


# ---------------------------------------------------------------------------
# Phase 6.9: Execution-time resolution bridge
# ---------------------------------------------------------------------------


def compare_resolutions(
    preview_legs: list[dict],
    fresh_result: ResolutionResult,
) -> list[dict]:
    """Compare preview resolution against fresh execution-time resolution.

    Returns a list of change dicts: [{position, field, preview_value, fresh_value}].
    """
    changes = []
    fresh_by_pos = {leg.position: leg for leg in fresh_result.legs}
    for preview_leg in preview_legs:
        pos = preview_leg.get("position", 0)
        fresh = fresh_by_pos.get(pos)
        if fresh is None:
            continue
        preview_strike = preview_leg.get("resolved_strike")
        preview_expiry = preview_leg.get("resolved_expiry")
        if preview_strike is not None and fresh.resolved_strike != preview_strike:
            changes.append({
                "position": pos,
                "field": "strike",
                "preview_value": preview_strike,
                "fresh_value": fresh.resolved_strike,
            })
        if preview_expiry is not None and fresh.resolved_expiry != preview_expiry:
            changes.append({
                "position": pos,
                "field": "expiry",
                "preview_value": preview_expiry,
                "fresh_value": fresh.resolved_expiry,
            })
    return changes


def resolution_changes_status(changes: list[dict]) -> str:
    """Determine the change status from a list of detected changes."""
    if not changes:
        return "UNCHANGED"
    has_strike = any(c["field"] == "strike" for c in changes)
    has_expiry = any(c["field"] == "expiry" for c in changes)
    if has_strike and has_expiry:
        return "CHANGED_BOTH"
    if has_strike:
        return "CHANGED_STRIKE"
    return "CHANGED_EXPIRY"


def build_execution_legs_from_resolution(
    resolved_legs: list[ResolvedLegOutput],
    symbol: str,
) -> list[dict]:
    """Convert resolved legs to ExecutionLegIn-compatible dicts."""
    return [
        {
            "symbol": symbol,
            "expiration_date": leg.resolved_expiry,
            "strike_price": leg.resolved_strike,
            "option_type": leg.option_type,
            "action": leg.action,
            "quantity": leg.quantity,
            "lot_size": leg.lot_size,
        }
        for leg in resolved_legs
    ]


def _is_one_strike_step(
    preview_strike: float,
    fresh_strike: float,
    chain_step: float | None,
) -> bool:
    """Determine if a strike change is within one chain strike step.

    Uses the actual chain strike spacing, not a hardcoded value.
    When chain_step is unknown, treats any change as material.
    """
    if chain_step is None or chain_step <= 0:
        return False  # Unknown step → treat as material change
    diff = abs(fresh_strike - preview_strike)
    return diff <= chain_step + 0.001  # small epsilon for float comparison


def validate_execution_resolution(
    fresh_result: ResolutionResult,
    confirmed_strikes: dict[int, float] | None = None,
    confirmed_expiries: dict[int, str] | None = None,
    changes: list[dict] | None = None,
) -> tuple[bool, list[str]]:
    """Validate that a fresh resolution is safe to execute.

    Defense-in-depth: always compares confirmed values against the fresh
    resolution. Never trusts a boolean — validates actual reviewed values.

    One-strike-step policy:
      - Strike within 1 chain step of preview: auto-execute (no confirmation needed)
      - Strike > 1 chain step from preview: block, require explicit confirmation
      - Expiry changed: always block, require explicit confirmation

    If confirmed values are provided but don't match the fresh resolution,
    execution is blocked (old confirmation ≠ new resolution authorization).

    Returns (ok, errors).
    """
    errors = []
    chain_step = fresh_result.chain_strike_step

    # 1. Resolution must have succeeded
    if fresh_result.status == "FAILED":
        errors.extend(fresh_result.errors)
        return False, errors

    # 2. All legs must be resolved
    if not fresh_result.legs:
        errors.append("No legs could be resolved.")
        return False, errors

    # 3. All prices must be available (not stale, not unavailable)
    for leg in fresh_result.legs:
        if leg.price_status == "unavailable":
            errors.append(
                f"Market data unavailable for {leg.option_type.upper()} "
                f"{leg.resolved_strike:g} ({leg.resolved_expiry})."
            )
        elif leg.price_status == "stale":
            errors.append(
                f"Market data is stale for {leg.option_type.upper()} "
                f"{leg.resolved_strike:g} ({leg.resolved_expiry}). "
                f"Please refresh and try again."
            )

    # 4. Compare confirmed values against fresh resolution.
    #    The frontend always sends the preview's resolved values as the
    #    confirmation baseline. The server compares these against the fresh
    #    resolution to detect material changes.
    #
    #    Policy:
    #      a) No confirmed values provided → reject (TOCTOU protection)
    #      b) Confirmed value matches fresh → OK
    #      c) Confirmed value differs from fresh:
    #         - Strike within 1 chain step → auto-execute (small ATM drift)
    #         - Strike > 1 chain step → block, needs re-confirmation
    #         - Expiry changed → always block, needs re-confirmation
    if changes:
        if not confirmed_strikes and not confirmed_expiries:
            errors.append(
                "Resolution has changed since preview but no confirmation was provided. "
                "Please re-preview and confirm the updated values."
            )
            return False, errors

        for change in changes:
            pos = change["position"]
            fresh_leg = next((l for l in fresh_result.legs if l.position == pos), None)
            if fresh_leg is None:
                continue

            if change["field"] == "strike":
                confirmed_strike = confirmed_strikes.get(pos) if confirmed_strikes else None
                if confirmed_strike is not None:
                    # Confirmed value exists — compare against fresh
                    if confirmed_strike == fresh_leg.resolved_strike:
                        continue  # Exact match — OK
                    # Confirmed value differs from fresh — check one-step policy
                    if _is_one_strike_step(confirmed_strike, fresh_leg.resolved_strike, chain_step):
                        continue  # Within 1 chain step — auto-execute
                    # Material change — block
                    errors.append(
                        f"Strike for leg {pos + 1} changed from {confirmed_strike:g} "
                        f"to {fresh_leg.resolved_strike:g} (>{1 if chain_step is None else round((fresh_leg.resolved_strike - confirmed_strike) / chain_step, 1):g} chain steps). "
                        f"Please re-preview and confirm."
                    )
                else:
                    # No confirmed value for a changed strike — block
                    errors.append(
                        f"Strike for leg {pos + 1} changed ({change['preview_value']:g} → "
                        f"{change['fresh_value']:g}) but no confirmation was provided."
                    )

            elif change["field"] == "expiry":
                confirmed_expiry = confirmed_expiries.get(pos) if confirmed_expiries else None
                if confirmed_expiry is not None:
                    if confirmed_expiry == fresh_leg.resolved_expiry:
                        continue  # Exact match — OK
                    # Expiry changed — always block (no one-step tolerance for expiry)
                    errors.append(
                        f"Expiry for leg {pos + 1} changed from {confirmed_expiry} "
                        f"to {fresh_leg.resolved_expiry}. Please re-preview and confirm."
                    )
                else:
                    errors.append(
                        f"Expiry for leg {pos + 1} changed ({change['preview_value']} → "
                        f"{change['fresh_value']}) but no confirmation was provided."
                    )

    return len(errors) == 0, errors
