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

# Canonical GEX provenance source values. Keep this set small and explicit so
# downstream analytics can rely on stable values.
DATA_SOURCE_ANALYTICS_TOKEN = "analytics_token"
DATA_SOURCE_BROKER_OAUTH = "broker_oauth"
DATA_SOURCE_API_UPLOAD = "api_upload"
VALID_DATA_SOURCES = frozenset({
    DATA_SOURCE_ANALYTICS_TOKEN,
    DATA_SOURCE_BROKER_OAUTH,
    DATA_SOURCE_API_UPLOAD,
})
_CONNECTION_REQUIRED_SOURCES = frozenset({
    DATA_SOURCE_ANALYTICS_TOKEN,
    DATA_SOURCE_BROKER_OAUTH,
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_gex_snapshot(
    db: Session,
    snapshot: dict,
    owner_id: str | None = None,
    *,
    connection_id: str | None = None,
    data_source: str | None = None,
) -> int:
    """Persist one GEX snapshot; return 1 if stored, 0 if invalid.

    Uses explicit commit with rollback-on-failure for transaction safety.

    Phase 8F/10.2B-6: Provenance fields:
      - owner_id: StrikeNova user ID that owns this snapshot
      - connection_id: BrokerConnection ID that authorized the capture
      - data_source: "analytics_token", "broker_oauth", or "api_upload"

    User-authorized GEX sources (Analytics Token / Broker OAuth) require an
    owning user and exact broker connection. API uploads are the explicit
    provenance case where connection_id is not applicable.

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

    if data_source is not None:
        data_source = str(data_source).strip().lower()
        if data_source not in VALID_DATA_SOURCES:
            return 0
        if not owner_id:
            return 0
        if data_source in _CONNECTION_REQUIRED_SOURCES:
            if not connection_id:
                return 0
        elif data_source == DATA_SOURCE_API_UPLOAD and connection_id is not None:
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
    sweep_data = snapshot.get("sweepData")

    try:
        db.add(
            GexSnapshot(
                owner_id=owner_id,
                connection_id=connection_id,
                data_source=data_source,
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
                sweep_data=json.dumps(sweep_data, ensure_ascii=False) if sweep_data is not None else None,
            )
        )
        db.commit()
        return 1
    except Exception:
        db.rollback()
        raise


def get_gex_snapshots(
    db: Session,
    symbol: str,
    expiry: str | None = None,
    limit: int = 200,
    since: datetime | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    """Query stored GEX snapshots, oldest-first, optionally filtered.

    Phase 8F: when ``owner_id`` is provided, only returns snapshots
    belonging to that authenticated session.

    ``since`` filters to snapshots captured after the given datetime.
    Results are returned oldest-first so consumers can compute sequential ΔGEX.
    """
    stmt = select(GexSnapshot).where(GexSnapshot.symbol == symbol.upper())
    if expiry:
        stmt = stmt.where(GexSnapshot.expiry == expiry)
    if since:
        stmt = stmt.where(GexSnapshot.captured_at >= since)
    if owner_id:
        stmt = stmt.where(GexSnapshot.owner_id == owner_id)
    stmt = stmt.order_by(GexSnapshot.captured_at.asc()).limit(max(1, limit))
    return [_row_to_dict(row) for row in db.scalars(stmt)]


def get_latest_snapshot(
    db: Session,
    symbol: str,
    expiry: str | None = None,
    owner_id: str | None = None,
) -> dict | None:
    """Get the most recent GEX snapshot for a symbol/expiry.

    Phase 8F: when ``owner_id`` is provided, only returns snapshots
    belonging to that authenticated session.
    """
    stmt = select(GexSnapshot).where(GexSnapshot.symbol == symbol.upper())
    if expiry:
        stmt = stmt.where(GexSnapshot.expiry == expiry)
    if owner_id:
        stmt = stmt.where(GexSnapshot.owner_id == owner_id)
    stmt = stmt.order_by(GexSnapshot.captured_at.desc()).limit(1)
    row = db.scalars(stmt).first()
    return _row_to_dict(row) if row else None


def prune_gex_snapshots(db: Session, retention_days: int = 90) -> int:
    """Delete snapshots older than ``retention_days``; return rows deleted.

    Uses explicit commit with rollback-on-failure for safety.
    """
    cutoff = _utcnow() - timedelta(days=max(1, retention_days))
    try:
        result = db.execute(delete(GexSnapshot).where(GexSnapshot.captured_at < cutoff))
        db.commit()
        return result.rowcount or 0
    except Exception:
        db.rollback()
        raise


def count_gex_snapshots(db: Session, symbol: str | None = None, owner_id: str | None = None) -> int:
    """Count stored snapshots, optionally filtered by symbol and owner."""
    stmt = select(func.count(GexSnapshot.id))
    if symbol:
        stmt = stmt.where(GexSnapshot.symbol == symbol.upper())
    if owner_id:
        stmt = stmt.where(GexSnapshot.owner_id == owner_id)
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
        "owner_id": row.owner_id,
        "connection_id": row.connection_id,
        "data_source": row.data_source,
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
        "sweepData": json.loads(row.sweep_data) if row.sweep_data else None,
    }
