"""Phase 6.8C: Inline Strategy Resolution Endpoint.

POST /paper/resolve — Resolve arbitrary legs (not tied to a saved template)
against live broker chain data. Returns resolved strikes, expiries, and
current market prices WITHOUT creating any execution records.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import get_session_id
from app.routers.paper import require_session
from app.schemas import (
    ResolutionInlineRequestIn,
    ResolutionOut,
    ResolutionLegOut,
)


router = APIRouter()


@router.post("/resolve", response_model=ResolutionOut)
async def resolve_inline(
    request: ResolutionInlineRequestIn,
    session_id: str | None = Depends(get_session_id),
):
    """POST /paper/resolve — Resolve inline legs against live broker chain.

    Resolves each leg's formula (strike_mode, expiry_mode, etc.) against
    the live option chain and returns fully resolved legs with current
    market prices.

    CRITICAL: This NEVER creates execution records. It is read-only.
    The resolved legs can then be submitted to POST /paper/executions.
    """
    from app.services.template_resolution import resolve_legs

    user_id, access_token = require_session(session_id)

    # Convert schema legs to dicts
    legs = []
    for i, leg in enumerate(request.legs):
        legs.append({
            "position": i,
            "action": leg.action,
            "option_type": leg.option_type,
            "strike": leg.strike,
            "expiry": leg.expiry,
            "quantity": leg.quantity,
            "lot_size": leg.lot_size,
            "strike_mode": leg.strike_mode,
            "strike_offset": leg.strike_offset,
            "target_delta": leg.target_delta,
            "expiry_mode": leg.expiry_mode,
            "expiry_dte_min": leg.expiry_dte_min,
            "expiry_dte_max": leg.expiry_dte_max,
        })

    result = await resolve_legs(
        access_token=access_token,
        symbol=request.symbol,
        legs=legs,
    )

    # Convert to response schema
    leg_outs = []
    for leg in result.legs:
        leg_outs.append(ResolutionLegOut(
            position=leg.position,
            action=leg.action,
            option_type=leg.option_type,
            quantity=leg.quantity,
            lot_size=leg.lot_size,
            resolved_strike=leg.resolved_strike,
            resolved_expiry=leg.resolved_expiry,
            strike_mode_used=leg.strike_mode_used,
            expiry_mode_used=leg.expiry_mode_used,
            current_price=leg.current_price,
            price_status=leg.price_status,
            quote_timestamp=leg.quote_timestamp,
            ltp=leg.ltp,
            warnings=leg.warnings,
            symbol=leg.symbol,
            expiration_date=leg.expiration_date,
            strike_price=leg.strike_price,
        ))

    return ResolutionOut(
        status=result.status,
        symbol=result.symbol,
        legs=leg_outs,
        errors=result.errors,
        warnings=result.warnings,
        template_id=result.template_id,
        template_name=result.template_name,
    )
