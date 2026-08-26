"""Contract metadata registry — Phase 7.8F (Expired Instruments Adapter & Registry).

Stores and retrieves authoritative per-instrument historical contract
metadata sourced from the Upstox Get Expired Option Contracts API.

**Immutability rule:**  Once a valid ``lot_size`` is stored for an
``instrument_key``, it is NEVER overwritten.  This is the single most
important invariant in the contract-metadata layer — it guarantees
reproducibility of any future GEX / exposure calculation.

Architecture:
  - The candle pipeline (nifty_candles) is completely independent of this
    module.  Candles are pure OHLCV records.
  - This module is consumed ONLY by future phases (7.9+) that reconstruct
    historical option chains and compute GEX.
  - Missing contract metadata (lot_size = None) is a valid state — the
    system degrades safely.  We never substitute today's lot size.

Source:
  - ``UPSTOX_EXPIRED_INSTRUMENTS`` — Upstox Get Expired Option Contracts API
  - NSE circulars/specifications may be used as independent validation, NOT
    as a replacement source when authoritative Upstox metadata exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContractSpec

logger = logging.getLogger(__name__)

# Source identifier stored in every row
SOURCE_UPSTOX_EXPIRED = "UPSTOX_EXPIRED_INSTRUMENTS"


# ---------------------------------------------------------------------------
# Public lookup interface
# ---------------------------------------------------------------------------

def get_contract_specification(
    db: Session,
    instrument_key: str,
) -> dict | None:
    """Resolve historical contract specification by instrument_key.

    Returns the full specification dict, or ``None`` if no record exists.

    Returns
    -------
    dict or None
        A dict with keys: ``instrument_key``, ``underlying``,
        ``underlying_key``, ``expiry``, ``strike_price``,
        ``instrument_type``, ``lot_size``, ``minimum_lot``,
        ``freeze_quantity``, ``tick_size``, ``trading_symbol``,
        ``segment``, ``exchange``, ``weekly``, ``source``,
        ``source_reference``, ``fetched_at``.

        ``lot_size`` may be ``None`` when the historical value is unknown.
        Callers MUST handle ``None`` — never substitute today's lot size.

    Notes
    -----
    - NEVER silently substitutes the current lot size.
    - NEVER infers historical lot_size from the current lot size.
    - Returns ``None`` (not a default) when the instrument is unknown.
    """
    row = db.execute(
        select(ContractSpec).where(ContractSpec.instrument_key == instrument_key)
    ).scalar_one_or_none()

    if row is None:
        return None

    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Population from Upstox API response
# ---------------------------------------------------------------------------

@dataclass
class UpsertResult:
    """Result of attempting to upsert a single contract specification."""
    instrument_key: str
    action: str          # "inserted" | "idempotent" | "conflict" | "filled_lot_size"
    lot_size: int | None = None
    message: str = ""


def upsert_contract_spec(
    db: Session,
    contract: dict,
    source: str = SOURCE_UPSTOX_EXPIRED,
    source_reference: str = "",
) -> UpsertResult:
    """Upsert one contract from the Upstox Expired Option Contracts API.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    contract:
        A single contract dict as returned by the Upstox API, containing
        at minimum: ``instrument_key``, ``expiry``, ``lot_size``,
        ``minimum_lot``, ``freeze_quantity``, ``tick_size``,
        ``strike_price``, ``instrument_type``, ``underlying_key``,
        ``underlying_symbol``, ``trading_symbol``, ``segment``,
        ``exchange``, ``weekly``.
    source:
        Provenance identifier (default ``UPSTOX_EXPIRED_INSTRUMENTS``).
    source_reference:
        Human-readable audit trail (e.g. API endpoint + params).

    Returns
    -------
    UpsertResult
        Describes what happened: inserted, idempotent (same data),
        conflict (existing lot_size differs), or filled_lot_size
        (existing row had NULL lot_size, now filled).

    Immutability
    ------------
    - New row → insert with whatever lot_size the API returned.
    - Existing row, same lot_size → idempotent no-op.
    - Existing row, NULL lot_size + valid API lot_size → fill it.
    - Existing row, valid lot_size + DIFFERENT API lot_size → DO NOT
      overwrite.  Report conflict.  Preserve the existing authoritative
      value.
    """
    instrument_key = contract.get("instrument_key", "")
    if not instrument_key:
        return UpsertResult(
            instrument_key="<missing>",
            action="error",
            message="contract dict has no instrument_key",
        )

    api_lot_size = contract.get("lot_size")
    api_minimum_lot = contract.get("minimum_lot")

    existing = db.execute(
        select(ContractSpec).where(ContractSpec.instrument_key == instrument_key)
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if existing is None:
        # --- New row: insert ---
        row = ContractSpec(
            instrument_key=instrument_key,
            underlying=contract.get("underlying_symbol", contract.get("name", "")),
            underlying_key=contract.get("underlying_key", ""),
            expiry=contract.get("expiry", ""),
            strike_price=float(contract.get("strike_price", 0)),
            instrument_type=contract.get("instrument_type", ""),
            lot_size=api_lot_size,
            minimum_lot=api_minimum_lot,
            freeze_quantity=contract.get("freeze_quantity"),
            tick_size=float(contract["tick_size"]) if contract.get("tick_size") is not None else None,
            trading_symbol=contract.get("trading_symbol", ""),
            segment=contract.get("segment", ""),
            exchange=contract.get("exchange", ""),
            weekly=bool(contract.get("weekly", False)),
            source=source,
            source_reference=source_reference,
            fetched_at=now,
        )
        db.add(row)
        db.flush()
        return UpsertResult(
            instrument_key=instrument_key,
            action="inserted",
            lot_size=api_lot_size,
        )

    # --- Existing row ---
    existing_lot_size = existing.lot_size

    # Case 1: existing lot_size is NULL → fill it from API
    if existing_lot_size is None and api_lot_size is not None:
        existing.lot_size = api_lot_size
        if existing.minimum_lot is None and api_minimum_lot is not None:
            existing.minimum_lot = api_minimum_lot
        existing.source = source
        existing.source_reference = source_reference
        existing.fetched_at = now
        db.flush()
        return UpsertResult(
            instrument_key=instrument_key,
            action="filled_lot_size",
            lot_size=api_lot_size,
            message=f"Filled NULL lot_size with {api_lot_size}",
        )

    # Case 2: existing lot_size is the same → idempotent no-op
    if existing_lot_size == api_lot_size:
        return UpsertResult(
            instrument_key=instrument_key,
            action="idempotent",
            lot_size=api_lot_size,
        )

    # Case 3: existing lot_size is valid AND different from API → CONFLICT
    # DO NOT overwrite.  Preserve the existing authoritative value.
    if existing_lot_size is not None and api_lot_size is not None and existing_lot_size != api_lot_size:
        logger.warning(
            "CONFLICT lot_size for %s: existing=%d, api=%d — preserving existing",
            instrument_key, existing_lot_size, api_lot_size,
        )
        return UpsertResult(
            instrument_key=instrument_key,
            action="conflict",
            lot_size=existing_lot_size,
            message=(
                f"CONFLICT: existing lot_size={existing_lot_size} "
                f"differs from API lot_size={api_lot_size} — preserving existing"
            ),
        )

    # Case 4: both NULL → nothing to update
    return UpsertResult(
        instrument_key=instrument_key,
        action="idempotent",
        lot_size=None,
    )


def upsert_contract_specs(
    db: Session,
    contracts: list[dict],
    source: str = SOURCE_UPSTOX_EXPIRED,
    source_reference: str = "",
) -> list[UpsertResult]:
    """Batch upsert: insert or validate a list of contract dicts.

    Commits at the end.  Returns a list of UpsertResult, one per contract.
    """
    results: list[UpsertResult] = []
    for contract in contracts:
        result = upsert_contract_spec(
            db, contract, source=source, source_reference=source_reference,
        )
        results.append(result)
    db.commit()
    return results


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def count_contract_specs(db: Session, underlying: str | None = None) -> int:
    """Count stored contract specifications."""
    from sqlalchemy import func
    stmt = select(func.count(ContractSpec.id))
    if underlying:
        stmt = stmt.where(ContractSpec.underlying == underlying.upper())
    return db.scalar(stmt) or 0


def get_all_expiry_dates(db: Session, underlying: str | None = None) -> list[str]:
    """Return distinct expiry dates stored in the registry, sorted ascending."""
    from sqlalchemy import distinct
    stmt = select(distinct(ContractSpec.expiry))
    if underlying:
        stmt = stmt.where(ContractSpec.underlying == underlying.upper())
    stmt = stmt.order_by(ContractSpec.expiry.asc())
    return [row[0] for row in db.execute(stmt).all()]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _row_to_dict(row: ContractSpec) -> dict:
    return {
        "instrument_key": row.instrument_key,
        "underlying": row.underlying,
        "underlying_key": row.underlying_key,
        "expiry": row.expiry,
        "strike_price": row.strike_price,
        "instrument_type": row.instrument_type,
        "lot_size": row.lot_size,
        "minimum_lot": row.minimum_lot,
        "freeze_quantity": row.freeze_quantity,
        "tick_size": row.tick_size,
        "trading_symbol": row.trading_symbol,
        "segment": row.segment,
        "exchange": row.exchange,
        "weekly": row.weekly,
        "source": row.source,
        "source_reference": row.source_reference,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
    }
