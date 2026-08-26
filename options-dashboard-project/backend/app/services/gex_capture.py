"""Live GEX Snapshot Capture Service — Phase 8B.

Orchestrates the complete capture pipeline:

    Customer's Upstox session
            ↓
    Option chain (via existing broker adapter)
            ↓
    LiveGexService (Phase 8A — canonical calculation)
            ↓
    Data quality validation
            ↓
    Snapshot dict conversion
            ↓
    Deduplication check
            ↓
    gex_snapshots (existing persistence layer)

Design rules:
- Reuses existing ``LiveGexService`` as the single source of GEX truth.
- Reuses existing ``gex_history.record_gex_snapshot()`` for persistence.
- Does NOT duplicate the GEX formula.
- Does NOT fabricate GEX values.
- Handles incomplete/stale chain data safely.
- Capture failures are logged and retried on the next interval.
- Never logs access tokens, API secrets, or authorization codes.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import GexSnapshot
from app.services.gex_history import (
    get_gex_snapshots,
    record_gex_snapshot,
    prune_gex_snapshots,
)
from app.services.live_gex import (
    GexCalculationResult,
    GexStatus,
    LiveGexService,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_capture_interval_seconds() -> int:
    """Return the configured capture interval in seconds.

    Uses ``GEX_HISTORY_SAMPLE_SECONDS`` from config, defaulting to 60s.
    """
    return getattr(settings, "GEX_HISTORY_SAMPLE_SECONDS", 60)


def get_retention_days() -> int:
    """Return the configured retention period in days."""
    return getattr(settings, "GEX_HISTORY_RETENTION_DAYS", 90)


# ---------------------------------------------------------------------------
# Snapshot conversion
# ---------------------------------------------------------------------------

def _result_to_snapshot_dict(
    result: GexCalculationResult,
    *,
    expiry: str | None = None,
    symbol: str | None = None,
) -> dict:
    """Convert a LiveGexService result to the snapshot dict expected by
    ``record_gex_snapshot()``.

    This is the ONLY place where the LiveGexService output shape is
    translated to the persistence layer's expected input shape.
    """
    now = datetime.now(timezone.utc)

    # Use the result's own fields; allow explicit overrides
    effective_symbol = symbol or result.symbol or "NIFTY"
    effective_expiry = expiry or result.expiry or ""

    # Build strike-level data for the snapshot
    strike_data = []
    for s in result.strikes:
        strike_data.append({
            "strike": s.strike,
            "callGamma": s.call_gamma,
            "callOi": s.call_oi,
            "callGex": s.call_gex,
            "putGamma": s.put_gamma,
            "putOi": s.put_oi,
            "putGex": s.put_gex,
            "netGex": s.net_gex,
            "status": s.status,
        })

    return {
        "symbol": effective_symbol,
        "expiry": effective_expiry,
        "spot": result.spot,
        "methodology": result.methodology,
        "signConvention": result.sign_convention,
        "callGex": result.call_gex,
        "putGex": result.put_gex,
        "netGex": result.net_gex,
        "availabilityStatus": result.availability_status,
        "validStrikeCount": result.valid_strike_count,
        "totalStrikeCount": result.total_strike_count,
        "chainAgeMs": result.chain_age_ms,
        "capturedAt": result.captured_at or now.isoformat(),
        "strikeData": strike_data,
        "expiryData": [],
        "methodologyMetadata": result.methodology_metadata,
        "sweepData": None,
    }


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _is_duplicate(
    db: Session,
    symbol: str,
    expiry: str | None,
    captured_at: datetime,
    tolerance_seconds: int = 60,
) -> Optional[int]:
    """Check whether a snapshot with similar identity already exists.

    Returns the existing snapshot ID if duplicate, None otherwise.

    Deduplication criteria: same symbol + expiry + captured_at within
    tolerance_seconds.
    """
    cutoff = captured_at - timedelta(seconds=tolerance_seconds)
    recent = get_gex_snapshots(db, symbol=symbol, expiry=expiry, limit=1, since=cutoff)
    if recent:
        last = recent[-1]
        last_cat = last.get("capturedAt")
        if last_cat:
            try:
                last_dt = datetime.fromisoformat(last_cat.replace("Z", "+00:00"))
                cat_naive = captured_at.replace(tzinfo=None)
                last_naive = last_dt.replace(tzinfo=None)
                if abs((cat_naive - last_naive).total_seconds()) < tolerance_seconds:
                    return last.get("id")
            except (ValueError, TypeError):
                pass
    return None


# ---------------------------------------------------------------------------
# GexCaptureService
# ---------------------------------------------------------------------------

class GexCaptureService:
    """Captures and persists live GEX snapshots.

    Stateless per-call: each ``capture_once()`` invocation fetches a fresh
    chain, computes GEX, validates, and persists.  No background state is
    held by the service itself.

    Usage::

        service = GexCaptureService()
        result = service.capture_once(db, chain_data, expiry="2026-08-28")
    """

    def __init__(self, gex_service: LiveGexService | None = None):
        self._gex_service = gex_service or LiveGexService()

    def capture_once(
        self,
        db: Session,
        chain: dict,
        *,
        expiry: str | None = None,
        symbol: str | None = None,
    ) -> dict:
        """Capture one GEX snapshot from the provided chain data.

        Args:
            db: Database session.
            chain: Canonical option chain from Upstox adapter.
            expiry: Expiry date override (if not in chain).
            symbol: Symbol override (if not in chain).

        Returns:
            dict with keys: status, snapshot_id, symbol, expiry, net_gex, etc.
        """
        now = datetime.now(timezone.utc)

        # Validate chain has usable data
        spot = chain.get("underlying_spot_price") if chain else None
        effective_symbol = (symbol or (chain or {}).get("symbol") or "NIFTY").upper()
        effective_expiry = expiry or (chain or {}).get("expiry_date") or ""

        if not chain or not isinstance(chain, dict):
            logger.warning(
                "GEX capture skipped: no chain data",
                extra={"symbol": effective_symbol, "reason": "MISSING_CHAIN"},
            )
            return {"status": "skipped", "reason": "missing_chain", "symbol": effective_symbol}

        chain_rows = chain.get("chain") or []
        if not chain_rows:
            logger.warning(
                "GEX capture skipped: empty chain",
                extra={"symbol": effective_symbol, "expiry": effective_expiry, "reason": "EMPTY_CHAIN"},
            )
            return {"status": "skipped", "reason": "empty_chain", "symbol": effective_symbol}

        # Compute GEX using the canonical Phase 8A engine
        try:
            result = self._gex_service.calculate(chain)
        except Exception as exc:
            logger.error(
                "GEX capture failed: calculation error",
                extra={"symbol": effective_symbol, "error": str(exc)},
                exc_info=True,
            )
            return {"status": "error", "reason": "calculation_error", "symbol": effective_symbol}

        # Validate the result is persistable
        # Skip if spot is None, NaN, or infinite — cannot persist to DB
        spot_val = result.spot
        spot_valid = (
            spot_val is not None
            and isinstance(spot_val, (int, float))
            and math.isfinite(spot_val)
            and spot_val > 0
        )
        if not spot_valid:
            logger.warning(
                "GEX capture skipped: invalid spot",
                extra={"symbol": effective_symbol, "expiry": effective_expiry, "spot": spot_val},
            )
            return {"status": "skipped", "reason": "invalid_spot", "symbol": effective_symbol}

        # Convert to snapshot dict
        snapshot_dict = _result_to_snapshot_dict(result, expiry=effective_expiry, symbol=effective_symbol)

        # Parse captured_at for deduplication
        captured_at_str = snapshot_dict.get("capturedAt", "")
        try:
            captured_at = datetime.fromisoformat(captured_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            captured_at = now

        # Deduplication check
        existing_id = _is_duplicate(db, effective_symbol, effective_expiry, captured_at)
        if existing_id is not None:
            logger.debug(
                "GEX capture deduplicated",
                extra={"symbol": effective_symbol, "expiry": effective_expiry, "existing_id": existing_id},
            )
            return {
                "status": "duplicate",
                "snapshot_id": existing_id,
                "symbol": effective_symbol,
                "expiry": effective_expiry,
                "net_gex": result.net_gex,
            }

        # Persist
        try:
            stored = record_gex_snapshot(db, snapshot_dict)
            if stored == 0:
                logger.warning(
                    "GEX capture failed: persistence rejected",
                    extra={"symbol": effective_symbol, "expiry": effective_expiry},
                )
                return {"status": "error", "reason": "persistence_rejected", "symbol": effective_symbol}

            # Get the ID of the stored snapshot
            latest = get_gex_snapshots(db, symbol=effective_symbol, expiry=effective_expiry, limit=1)
            snap_id = latest[-1].get("id") if latest else None

            logger.info(
                "GEX snapshot captured",
                extra={
                    "symbol": effective_symbol,
                    "expiry": effective_expiry,
                    "net_gex": result.net_gex,
                    "valid_strikes": result.valid_strike_count,
                    "total_strikes": result.total_strike_count,
                    "data_quality": result.availability_status,
                    "snapshot_id": snap_id,
                },
            )

            return {
                "status": "captured",
                "snapshot_id": snap_id,
                "symbol": effective_symbol,
                "expiry": effective_expiry,
                "net_gex": result.net_gex,
                "call_gex": result.call_gex,
                "put_gex": result.put_gex,
                "spot": result.spot,
                "data_quality": result.availability_status,
                "valid_strike_count": result.valid_strike_count,
                "total_strike_count": result.total_strike_count,
                "captured_at": captured_at_str,
            }

        except Exception as exc:
            logger.error(
                "GEX capture failed: persistence error",
                extra={"symbol": effective_symbol, "error": str(exc)},
                exc_info=True,
            )
            return {"status": "error", "reason": "persistence_error", "symbol": effective_symbol}


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------

def run_retention_cleanup(db: Session) -> int:
    """Prune old GEX snapshots based on configured retention.

    Returns the number of snapshots deleted.
    """
    days = get_retention_days()
    deleted = prune_gex_snapshots(db, retention_days=days)
    if deleted > 0:
        logger.info("GEX snapshot retention cleanup", extra={"retention_days": days, "deleted": deleted})
    return deleted
