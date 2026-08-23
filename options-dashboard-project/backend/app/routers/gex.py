"""GEX snapshot persistence API (Phase 7.6).

Endpoints:
  POST /gex/snapshots          — store a GEX snapshot
  GET  /gex/snapshots          — query stored snapshots (oldest-first)
  GET  /gex/snapshots/latest   — get most recent snapshot

All endpoints require session authentication (X-Session-Id header or
session_id cookie).  Snapshots are user-scoped via the session.

Snapshot data is market-data analytics only — no broker credentials,
no trading logic, no BUY/SELL signals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import get_session_id
from app.services import token_store
from app.services.gex_history import (
    record_gex_snapshot,
    get_gex_snapshots,
    get_latest_snapshot,
    count_gex_snapshots,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def require_session(session_id: str | None) -> str:
    """Validate the session and return the session_id."""
    token = token_store.get_token(session_id) if session_id else None
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in. Visit /auth/login first.")
    return session_id


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class GexSnapshotIn(BaseModel):
    """Incoming snapshot from the frontend.  Mirrors GEXSnapshot_v1."""
    symbol: str
    expiry: str | None = None
    spot: float
    methodology: str = "GEX_STANDARD_V1"
    signConvention: str = "NAIVE_DEALER_CONVENTION"
    callGex: float | None = None
    putGex: float | None = None
    netGex: float | None = None
    availabilityStatus: str = "available"
    validStrikeCount: int = 0
    totalStrikeCount: int = 0
    chainAgeMs: float | None = None
    capturedAt: str | None = None
    strikeData: list = Field(default_factory=list)
    expiryData: list = Field(default_factory=list)
    methodologyMetadata: dict = Field(default_factory=dict)
    sweepData: dict | None = None


class GexSnapshotOut(BaseModel):
    """Snapshot returned to the frontend."""
    id: int
    symbol: str
    expiry: str | None = None
    spot: float
    methodology: str
    signConvention: str
    callGex: float | None = None
    putGex: float | None = None
    netGex: float | None = None
    availabilityStatus: str
    validStrikeCount: int
    totalStrikeCount: int
    chainAgeMs: float | None = None
    capturedAt: str | None = None
    strikeData: list = Field(default_factory=list)
    expiryData: list = Field(default_factory=list)
    methodologyMetadata: dict = Field(default_factory=dict)
    sweepData: dict | None = None


class GexSnapshotListOut(BaseModel):
    snapshots: list[GexSnapshotOut]
    count: int
    symbol: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/snapshots", response_model=dict)
def create_snapshot(
    body: GexSnapshotIn,
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """POST /gex/snapshots — Store a GEX snapshot.

    Idempotent within 1-minute tolerance: same symbol + capturedAt within
    60 seconds → returns existing ID without inserting a duplicate.
    """
    require_session(session_id)

    snapshot_dict = body.model_dump()
    # Inject schema version for the persistence layer
    snapshot_dict.setdefault("schemaVersion", "GEXSnapshot_v1")

    # Idempotency: check for recent duplicate
    captured_at = snapshot_dict.get("capturedAt")
    if captured_at:
        try:
            cat_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            cat_dt = None
        if cat_dt is not None:
            since_cutoff = cat_dt - timedelta(seconds=60)
            recent = get_gex_snapshots(
                db,
                symbol=snapshot_dict["symbol"],
                expiry=snapshot_dict.get("expiry"),
                limit=1,
                since=since_cutoff,
            )
            if recent:
                last = recent[-1]
                last_cat = last.get("capturedAt")
                if last_cat:
                    try:
                        last_dt = datetime.fromisoformat(last_cat.replace("Z", "+00:00"))
                        # Normalize to naive UTC for comparison (SQLite strips tz)
                        cat_naive = cat_dt.replace(tzinfo=None)
                        last_naive = last_dt.replace(tzinfo=None)
                        if abs((cat_naive - last_naive).total_seconds()) < 60:
                            return {"ok": True, "id": last.get("id"), "duplicate": True}
                    except (ValueError, TypeError):
                        pass

    result = record_gex_snapshot(db, snapshot_dict)
    if result == 0:
        raise HTTPException(status_code=400, detail="Invalid snapshot data")

    # Get the ID of the just-inserted snapshot
    latest = get_latest_snapshot(db, snapshot_dict["symbol"], snapshot_dict.get("expiry"))
    snap_id = latest.get("id") if latest else None

    return {"ok": True, "id": snap_id, "duplicate": False}


@router.get("/snapshots", response_model=GexSnapshotListOut)
def list_snapshots(
    symbol: str = Query(..., description="Underlying symbol"),
    expiry: str | None = Query(None, description="Filter by expiry"),
    limit: int = Query(200, ge=1, le=500, description="Max snapshots"),
    since: str | None = Query(None, description="ISO-8601 timestamp filter"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /gex/snapshots — Query stored GEX snapshots (oldest-first)."""
    require_session(session_id)

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid 'since' timestamp")

    snapshots = get_gex_snapshots(db, symbol=symbol, expiry=expiry, limit=limit, since=since_dt)

    return GexSnapshotListOut(
        snapshots=[GexSnapshotOut(**s) for s in snapshots],
        count=len(snapshots),
        symbol=symbol.upper(),
    )


@router.get("/snapshots/latest", response_model=GexSnapshotOut | None)
def latest_snapshot(
    symbol: str = Query(..., description="Underlying symbol"),
    expiry: str | None = Query(None, description="Filter by expiry"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /gex/snapshots/latest — Get the most recent GEX snapshot."""
    require_session(session_id)

    snapshot = get_latest_snapshot(db, symbol=symbol, expiry=expiry)
    if snapshot is None:
        return None

    return GexSnapshotOut(**snapshot)


@router.get("/snapshots/count")
def snapshot_count(
    symbol: str | None = Query(None, description="Filter by symbol"),
    session_id: str | None = Depends(get_session_id),
    db: Session = Depends(get_db),
):
    """GET /gex/snapshots/count — Count stored snapshots."""
    require_session(session_id)
    return {"count": count_gex_snapshots(db, symbol=symbol)}
