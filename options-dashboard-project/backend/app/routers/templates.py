"""Phase 6.7: Strategy Template CRUD endpoints.

Persistent user-created strategy templates with strict user ownership.
Editing, renaming, duplicating or deleting a template NEVER affects
historical executions, positions, exposures, orders, journal or P&L.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import StrategyTemplate, StrategyTemplateLeg
from app.routers.deps import get_session_id
from app.routers.paper import require_session
from app.schemas import (
    ResolutionLegOut,
    ResolutionOut,
    StrategyTemplateCreateIn,
    StrategyTemplateLegOut,
    StrategyTemplateOut,
    StrategyTemplateUpdateIn,
)

router = APIRouter()


def _get_user_template(
    db: Session, user_id: str, template_id: int
) -> StrategyTemplate:
    """Fetch a template owned by the user, or raise 404."""
    template = db.scalar(
        select(StrategyTemplate)
        .options(joinedload(StrategyTemplate.legs))
        .where(
            StrategyTemplate.id == template_id,
            StrategyTemplate.user_id == user_id,
        )
    )
    if template is not None:
        # Force eager-load evaluation
        _ = template.legs
    if template is None:
        raise HTTPException(status_code=404, detail="Strategy template not found.")
    return template


def _template_out(template: StrategyTemplate) -> dict:
    """Serialize a StrategyTemplate to the response dict."""
    return {
        "id": template.id,
        "name": template.name,
        "symbol": template.symbol,
        "legs": [
            {
                "id": leg.id,
                "position": leg.position,
                "action": leg.action,
                "option_type": leg.option_type,
                "strike": leg.strike,
                "expiry": leg.expiry,
                "quantity": leg.quantity,
                "lot_size": leg.lot_size,
                "price": leg.price,
                # Phase 6.8B: dynamic formula fields
                "strike_mode": getattr(leg, "strike_mode", "fixed"),
                "strike_offset": getattr(leg, "strike_offset", None),
                "strike_offset_pct": getattr(leg, "strike_offset_pct", None),
                "target_delta": getattr(leg, "target_delta", None),
                "expiry_mode": getattr(leg, "expiry_mode", "fixed"),
                "expiry_dte_min": getattr(leg, "expiry_dte_min", None),
                "expiry_dte_max": getattr(leg, "expiry_dte_max", None),
                "formula_version": getattr(leg, "formula_version", 1),
            }
            for leg in sorted(template.legs, key=lambda l: l.position)
        ],
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


@router.get("/templates", response_model=list[StrategyTemplateOut])
def list_templates(
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /paper/templates — List the authenticated user's strategy templates."""
    user_id, _access_token = require_session(session_id)
    templates = db.scalars(
        select(StrategyTemplate)
        .options(joinedload(StrategyTemplate.legs))
        .where(StrategyTemplate.user_id == user_id)
        .order_by(StrategyTemplate.updated_at.desc())
    ).unique().all()
    return [_template_out(t) for t in templates]


@router.post("/templates", status_code=201, response_model=StrategyTemplateOut)
def create_template(
    body: StrategyTemplateCreateIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """POST /paper/templates — Create a new strategy template."""
    user_id, _access_token = require_session(session_id)

    # Check for duplicate name within user
    existing = db.scalar(
        select(StrategyTemplate).where(
            StrategyTemplate.user_id == user_id,
            StrategyTemplate.name == body.name,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A strategy template named '{body.name}' already exists.",
        )

    template = StrategyTemplate(
        user_id=user_id,
        name=body.name,
        symbol=body.symbol,
    )
    db.add(template)
    db.flush()  # get template.id

    for i, leg_in in enumerate(body.legs):
        leg = StrategyTemplateLeg(
            template_id=template.id,
            position=leg_in.position if leg_in.position else i,
            action=leg_in.action,
            option_type=leg_in.option_type,
            strike=leg_in.strike,
            expiry=leg_in.expiry,
            quantity=leg_in.quantity,
            lot_size=leg_in.lot_size,
            price=leg_in.price,
            # Phase 6.8B: dynamic formula fields
            strike_mode=leg_in.strike_mode,
            strike_offset=leg_in.strike_offset,
            strike_offset_pct=leg_in.strike_offset_pct,
            target_delta=leg_in.target_delta,
            expiry_mode=leg_in.expiry_mode,
            expiry_dte_min=leg_in.expiry_dte_min,
            expiry_dte_max=leg_in.expiry_dte_max,
            formula_version=leg_in.formula_version,
        )
        db.add(leg)

    db.commit()
    db.refresh(template)
    # Re-fetch with legs eagerly loaded
    db.refresh(template, ["legs"])
    return _template_out(template)


@router.get(
    "/templates/{template_id}", response_model=StrategyTemplateOut
)
def get_template(
    template_id: int,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /paper/templates/:id — Retrieve one strategy template."""
    user_id, _access_token = require_session(session_id)
    template = _get_user_template(db, user_id, template_id)
    return _template_out(template)


@router.put(
    "/templates/{template_id}", response_model=StrategyTemplateOut
)
def update_template(
    template_id: int,
    body: StrategyTemplateUpdateIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """PUT /paper/templates/:id — Update a strategy template.

    Partial update: only provided fields are changed.
    When ``legs`` is provided, the entire leg set is replaced (idempotent
    full replacement, not merge).
    """
    user_id, _access_token = require_session(session_id)
    template = _get_user_template(db, user_id, template_id)

    if body.name is not None:
        # Check for duplicate name (excluding this template)
        dup = db.scalar(
            select(StrategyTemplate).where(
                StrategyTemplate.user_id == user_id,
                StrategyTemplate.name == body.name,
                StrategyTemplate.id != template_id,
            )
        )
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A strategy template named '{body.name}' already exists.",
            )
        template.name = body.name

    if body.symbol is not None:
        template.symbol = body.symbol

    if body.legs is not None:
        # Full replacement of legs
        for leg in template.legs:
            db.delete(leg)
        db.flush()
        for i, leg_in in enumerate(body.legs):
            leg = StrategyTemplateLeg(
                template_id=template.id,
                position=leg_in.position if leg_in.position else i,
                action=leg_in.action,
                option_type=leg_in.option_type,
                strike=leg_in.strike,
                expiry=leg_in.expiry,
                quantity=leg_in.quantity,
                lot_size=leg_in.lot_size,
                price=leg_in.price,
                # Phase 6.8B: dynamic formula fields
                strike_mode=leg_in.strike_mode,
                strike_offset=leg_in.strike_offset,
                strike_offset_pct=leg_in.strike_offset_pct,
                target_delta=leg_in.target_delta,
                expiry_mode=leg_in.expiry_mode,
                expiry_dte_min=leg_in.expiry_dte_min,
                expiry_dte_max=leg_in.expiry_dte_max,
                formula_version=leg_in.formula_version,
            )
            db.add(leg)

    db.commit()
    db.refresh(template, ["legs"])
    return _template_out(template)


@router.post(
    "/templates/{template_id}/duplicate",
    status_code=201,
    response_model=StrategyTemplateOut,
)
def duplicate_template(
    template_id: int,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
    new_name: str | None = Query(default=None, description="Optional new name for the duplicate"),
):
    """POST /paper/templates/:id/duplicate — Duplicate a strategy template.

    Creates a deep copy with a new name (defaults to ``<original> (Copy)``).
    """
    user_id, _access_token = require_session(session_id)
    source = _get_user_template(db, user_id, template_id)

    dup_name = new_name or f"{source.name} (Copy)"
    # Check for duplicate name
    existing = db.scalar(
        select(StrategyTemplate).where(
            StrategyTemplate.user_id == user_id,
            StrategyTemplate.name == dup_name,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A strategy template named '{dup_name}' already exists.",
        )

    template = StrategyTemplate(
        user_id=user_id,
        name=dup_name,
        symbol=source.symbol,
    )
    db.add(template)
    db.flush()

    for leg in sorted(source.legs, key=lambda l: l.position):
        new_leg = StrategyTemplateLeg(
            template_id=template.id,
            position=leg.position,
            action=leg.action,
            option_type=leg.option_type,
            strike=leg.strike,
            expiry=leg.expiry,
            quantity=leg.quantity,
            lot_size=leg.lot_size,
            price=leg.price,
            # Phase 6.8B: copy all formula fields
            strike_mode=getattr(leg, "strike_mode", "fixed"),
            strike_offset=getattr(leg, "strike_offset", None),
            strike_offset_pct=getattr(leg, "strike_offset_pct", None),
            target_delta=getattr(leg, "target_delta", None),
            expiry_mode=getattr(leg, "expiry_mode", "fixed"),
            expiry_dte_min=getattr(leg, "expiry_dte_min", None),
            expiry_dte_max=getattr(leg, "expiry_dte_max", None),
            formula_version=getattr(leg, "formula_version", 1),
        )
        db.add(new_leg)

    db.commit()
    db.refresh(template, ["legs"])
    return _template_out(template)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """DELETE /paper/templates/:id — Delete a strategy template.

    Only deletes the template and its legs. NEVER affects historical
    executions, positions, exposures, orders, journal or P&L.
    """
    user_id, _access_token = require_session(session_id)
    template = _get_user_template(db, user_id, template_id)
    db.delete(template)
    db.commit()
    return None


@router.post(
    "/templates/{template_id}/resolve",
    response_model=ResolutionOut,
)
async def resolve_template(
    template_id: int,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """POST /paper/templates/:id/resolve — Resolve a saved template against live chain.

    Resolves every leg's formula (strike_mode, expiry_mode, etc.) against the
    live broker option chain and returns fully resolved legs with current
    market prices. Template metadata is preserved in the response.

    CRITICAL: This NEVER creates execution records. It is read-only.
    """
    from app.services.template_resolution import resolve_legs

    user_id, access_token = require_session(session_id)
    template = _get_user_template(db, user_id, template_id)

    # Convert template legs to dicts
    legs = []
    for i, leg in enumerate(template.legs):
        legs.append({
            "position": leg.position,
            "action": leg.action,
            "option_type": leg.option_type,
            "strike": leg.strike,
            "expiry": leg.expiry,
            "quantity": leg.quantity,
            "lot_size": leg.lot_size,
            "strike_mode": getattr(leg, "strike_mode", "fixed"),
            "strike_offset": getattr(leg, "strike_offset", None),
            "target_delta": getattr(leg, "target_delta", None),
            "expiry_mode": getattr(leg, "expiry_mode", "fixed"),
            "expiry_dte_min": getattr(leg, "expiry_dte_min", None),
            "expiry_dte_max": getattr(leg, "expiry_dte_max", None),
        })

    result = await resolve_legs(
        access_token=access_token,
        symbol=template.symbol,
        legs=legs,
        template_id=template.id,
        template_name=template.name,
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
