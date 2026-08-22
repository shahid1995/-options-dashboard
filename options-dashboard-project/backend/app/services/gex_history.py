"""Historical GEX snapshot persistence (Phase 7.3).

Records periodic GEX snapshots so that historical ΔGEX, migration, and
decomposition can be computed from stored data.  Follows the IV-history
precedent (``iv_history.py``) for sampling-interval / retention discipline.

Every snapshot stores enough raw inputs (broker gamma, OI, IV, spot,
strike, expiry) to reproduce the exact GEX calculation — no derived
values are assumed to be authoritative.

Capture is NOT wired into the live chain router yet (Phase 7.3a only
creates the persistence layer).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

from app.models import GexSnapshot

VALID_STATUSES = {"available", "partial", "unavailable", "invalid"}
DEFAULT_SOURCE = "upstox"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_gex_snapshot(db: Session, snapshot: dict) -> int:
    """Persist one GEX snapshot; return 1 if stored, 0 if invalid.

    Expected shape::

        {
            "symbol": "NIFTY",
            "expiry": "2026-08-28",
            "spot": 25512.0,
            "methodology": "GEX_STANDARD_V1",
            "signConvention": "NAIVE_DEALER_CONVENTION",
            "callGex": 125000000.0,
            "putGex": -98000000.0,
            "netGex": 27000000.0,
            "availabilityStatus": "available",
            "validStrikeCount": 20,
            "totalStrikeCount": 20,
            "chainAgeMs": 1200.0,
            "capturedAt": "2026-08-22T09:05:00+00:00",  # ISO 8601
            "strikeData": [ ... ],    # JSON-serialisable list
            "expiryData": [ ... ],    # JSON-serialisable list
            "methodologyMetadata": { ... },
        }

    Invalid / incomplete snapshots are skipped at the boundary.
    """
    if not snapshot:
        return 0

    symbol = str(snapshot.get("symbol", "")).upper().strip()
    expiry = snapshot.get("expiry")
    spot = snapshot.get("spot")
    status = str(snapshot.get("availabilityStatus", "")).lower().strip()

    if not symbol or not expiry:
        return 0
    if spot is None or not isinstance(spot, (int, float)) or spot <= 0:
        return 0
    if status not in VALID_STATUSES:
        return 0

    captured_at = snapshot.get("capturedAt")
    if captured_at is None:
        captured_at = _utcnow()
    elif isinstance(captured_at, str):
        captured_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))

    strike_data = snapshot.get("strikeData") or []
    expiry_data = snapshot.get("expiryData") or []
    methodology_metadata = snapshot.get("methodologyMetadata") or {}

    db.add(
        GexSnapshot(
            symbol=symbol,
            expiry=str(expiry),
            spot=float(spot),
            methodology=str(snapshot.get("methodology", "GEX_STANDARD_V1")),
            sign_convention=str(snapshot.get("signConvention", "NAIVE_DEALER_CONVENTION")),
            call_gex=_safe_float(snapshot.get("callGex")),
            put_gex=_safe_float(snapshot.get("putGex")),
            net_gex=_safe_float(snapshot.get("netGex")),
            availability_status=status,
            valid_strike_count=int(snapshot.get("validStrikeCount", 0)),
            total_strike_count=int(snapshot.get("totalStrikeCount", 0)),
            chain_age_ms=_safe_float(snapshot.get("chainAgeMs")),
            captured_at=captured_at,
            strike_data=json.dumps(strike_data, ensure_ascii=False),
            expiry_data=json.dumps(expiry_data, ensure_ascii=False),
            methodology_metadata=json.dumps(methodology_metadata, ensure_ascii=False),
        )
    )
    db.commit()
    return 1


def get_gex_snapshots(
    db: Session,
    symbol: str,
    expiry: str | None = None,
    limit: int = 200,
    since: datetime | None = None,
) -> list[dict]:
    """Query stored GEX snapshots, oldest-first, optionally filtered.

    ``since`` filters to snapshots captured after the given datetime.
    Results are returned oldest-first so consumers can compute sequential ΔGEX.
    """
    stmt = select(GexSnapshot).where(GexSnapshot.symbol == symbol.upper())
    if expiry:
        stmt = stmt.where(GexSnapshot.expiry == expiry)
    if since:
        stmt = stmt.where(GexSnapshot.captured_at >= since)
    stmt = stmt.order_by(GexSnapshot.captured_at.asc()).limit(max(1, limit))
    return [_row_to_dict(row) for row in db.scalars(stmt)]


def get_latest_snapshot(
    db: Session,
    symbol: str,
    expiry: str | None = None,
) -> dict | None:
    """Get the most recent GEX snapshot for a symbol/expiry."""
    stmt = select(GexSnapshot).where(GexSnapshot.symbol == symbol.upper())
    if expiry:
        stmt = stmt.where(GexSnapshot.expiry == expiry)
    stmt = stmt.order_by(GexSnapshot.captured_at.desc()).limit(1)
    row = db.scalars(stmt).first()
    return _row_to_dict(row) if row else None


def prune_gex_snapshots(db: Session, retention_days: int = 90) -> int:
    """Delete snapshots older than ``retention_days``; return rows deleted."""
    cutoff = _utcnow() - timedelta(days=max(1, retention_days))
    result = db.execute(delete(GexSnapshot).where(GexSnapshot.captured_at < cutoff))
    db.commit()
    return result.rowcount or 0


def count_gex_snapshots(db: Session, symbol: str | None = None) -> int:
    """Count stored snapshots, optionally filtered by symbol."""
    stmt = select(func.count(GexSnapshot.id))
    if symbol:
        stmt = stmt.where(GexSnapshot.symbol == symbol.upper())
    return db.scalar(stmt) or 0


# ---- Internal helpers --------------------------------------------------------


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if _is_finite(f) else None
    except (TypeError, ValueError):
        return None


def _is_finite(v) -> bool:
    return v == v and v != float("inf") and v != float("-inf")


def _row_to_dict(row: GexSnapshot) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "expiry": row.expiry,
        "spot": row.spot,
        "methodology": row.methodology,
        "signConvention": row.sign_convention,
        "callGex": row.call_gex,
        "putGex": row.put_gex,
        "netGex": row.net_gex,
        "availabilityStatus": row.availability_status,
        "validStrikeCount": row.valid_strike_count,
        "totalStrikeCount": row.total_strike_count,
        "chainAgeMs": row.chain_age_ms,
        "capturedAt": row.captured_at.isoformat() if row.captured_at else None,
        "strikeData": json.loads(row.strike_data) if row.strike_data else [],
        "expiryData": json.loads(row.expiry_data) if row.expiry_data else [],
        "methodologyMetadata": json.loads(row.methodology_metadata) if row.methodology_metadata else {},
    }
