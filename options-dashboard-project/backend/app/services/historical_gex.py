"""Historical GEX calculation service — Phase 7.8A.

Computes observed historical GEX from stored historical gamma, OI, and spot
data.  This is the MODEL → ANALYTICS bridge for the historical data pipeline:

    option_greeks (gamma) + option_candles (OI) + nifty_candles (spot)
        + contract_specs (strike, type, expiry)
                ↓
    HistoricalGexService
                ↓
    historical_gex table (observed GEX per option per timestamp)
                ↓
    Aggregation queries → strike-level / expiry-level / chain-level GEX

**Formula contract (Phase 7.1 — preserved exactly):**
    raw_gex = gamma × OI × spot² × 0.01
    CE → +raw_gex
    PE → −raw_gex

**Eligibility rules:**
    - gamma must be a positive finite number (gamma >= 0 is valid)
    - OI must be > 0 and finite
    - spot must be > 0 and finite
    - strike must be > 0 and finite
    - option_type must be "CE" or "PE"
    - Excluded rows carry an ``exclusion_reason`` — they are never silently
      dropped.

**Timestamp alignment:**
    - option_greeks.open_time is the canonical timestamp
    - spot is taken from option_greeks.spot (already aligned by the Greeks
      engine to the latest NIFTY close ≤ option candle open_time)
    - OI is taken from option_candles.open_time (exact match required)
    - No future spot data is ever used.

**Calculation versioning:**
    - "h_gex_v1" = first observed historical GEX version
    - Different versions coexist; never overwrite a different version.

**Idempotency:**
    - UNIQUE on (instrument_key, interval, open_time, calc_version)
    - Re-running persists the same data without duplicates.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import (
    OptionGreeks,
    OptionCandle,
    ContractSpec,
    NiftyCandle,
    HistoricalGexSnapshot,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALC_VERSION = "h_gex_v1"
CALC_MODEL = "GEX_STANDARD_V1"
SIGN_CONVENTION = "NAIVE_DEALER_CONVENTION"

# The Phase 7.1 formula factor
GEX_FACTOR = 0.01


# ---------------------------------------------------------------------------
# Eligibility / exclusion
# ---------------------------------------------------------------------------

class ExclusionReason(str, Enum):
    MISSING_GAMMA = "MISSING_GAMMA"
    INVALID_GAMMA = "INVALID_GAMMA"
    NEGATIVE_GAMMA = "NEGATIVE_GAMMA"
    MISSING_OI = "MISSING_OI"
    INVALID_OI = "INVALID_OI"
    ZERO_OI = "ZERO_OI"
    MISSING_SPOT = "MISSING_SPOT"
    INVALID_SPOT = "INVALID_SPOT"
    MISSING_STRIKE = "MISSING_STRIKE"
    INVALID_STRIKE = "INVALID_STRIKE"
    UNKNOWN_OPTION_TYPE = "UNKNOWN_OPTION_TYPE"
    MISSING_OPTION_TYPE = "MISSING_OPTION_TYPE"
    NON_SUCCESS_GREEKS = "NON_SUCCESS_GREEKS"


def _is_positive_finite(v) -> bool:
    """Check whether v is a positive finite number."""
    if v is None:
        return False
    try:
        n = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(n) and n > 0


def _is_nonnegative_finite(v) -> bool:
    """Check whether v is >= 0 and finite (gamma can be 0 at expiry)."""
    if v is None:
        return False
    try:
        n = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(n) and n >= 0


def _validate_option_row(
    gamma, oi, spot, strike, option_type
) -> Optional[ExclusionReason]:
    """Validate a single option row for GEX eligibility.

    Returns None if valid, or an ExclusionReason if invalid.
    Priority: option_type > spot > strike > gamma > OI
    """
    if option_type is None:
        return ExclusionReason.MISSING_OPTION_TYPE
    if option_type not in ("CE", "PE"):
        return ExclusionReason.UNKNOWN_OPTION_TYPE
    if not _is_positive_finite(spot):
        return ExclusionReason.MISSING_SPOT if spot is None else ExclusionReason.INVALID_SPOT
    if not _is_positive_finite(strike):
        return ExclusionReason.MISSING_STRIKE if strike is None else ExclusionReason.INVALID_STRIKE
    if gamma is None:
        return ExclusionReason.MISSING_GAMMA
    if not math.isfinite(float(gamma)):
        return ExclusionReason.INVALID_GAMMA
    if float(gamma) < 0:
        return ExclusionReason.NEGATIVE_GAMMA
    if not _is_positive_finite(oi):
        if oi is None:
            return ExclusionReason.MISSING_OI
        try:
            n = float(oi)
            if n <= 0:
                return ExclusionReason.ZERO_OI
        except (TypeError, ValueError):
            pass
        return ExclusionReason.INVALID_OI
    return None


# ---------------------------------------------------------------------------
# Core GEX calculation (Phase 7.1 contract — preserved exactly)
# ---------------------------------------------------------------------------

def compute_raw_gex(gamma: float, oi: float, spot: float) -> float:
    """Raw GEX = gamma * OI * spot^2 * 0.01.

    This is the Phase 7.1 mathematical contract.  Lot size is NOT part
    of the formula because OI is in number of contracts.
    """
    return gamma * oi * spot * spot * GEX_FACTOR


def compute_signed_gex(option_type: str, raw_gex: float) -> float:
    """Apply sign convention: CE → +raw, PE → −raw."""
    return raw_gex if option_type == "CE" else -raw_gex


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OptionGexRow:
    """One option-level GEX observation."""
    instrument_key: str
    interval: str
    open_time: datetime
    spot: float
    strike: float
    expiry: str
    option_type: str  # CE or PE
    gamma: float
    open_interest: float
    option_price: float
    lot_size: Optional[int]
    raw_gex: float
    signed_gex: float
    status: str = "SUCCESS"
    exclusion_reason: Optional[str] = None


@dataclass
class StrikeGex:
    """Aggregated GEX at one strike for one timestamp."""
    strike: float
    call_gex: float = 0.0
    put_gex: float = 0.0
    net_gex: float = 0.0
    call_oi: float = 0.0
    put_oi: float = 0.0
    call_gamma: float = 0.0
    put_gamma: float = 0.0
    has_call: bool = False
    has_put: bool = False


@dataclass
class ExpiryGex:
    """Aggregated GEX at one expiry for one timestamp."""
    expiry: str
    call_gex: float = 0.0
    put_gex: float = 0.0
    net_gex: float = 0.0
    valid_strikes: int = 0
    total_strikes: int = 0


@dataclass
class ChainGex:
    """Aggregated GEX across all expiries for one timestamp."""
    timestamp: datetime
    spot: float
    call_gex: float = 0.0
    put_gex: float = 0.0
    net_gex: float = 0.0
    by_strike: dict = field(default_factory=dict)  # {strike: StrikeGex}
    by_expiry: dict = field(default_factory=dict)   # {expiry: ExpiryGex}


@dataclass
class CalculationStats:
    """Audit trail for a GEX calculation run."""
    total_rows_examined: int = 0
    eligible_rows: int = 0
    excluded_rows: int = 0
    excluded_by_reason: dict = field(default_factory=dict)
    timestamps_processed: int = 0
    expiries_processed: int = 0
    strikes_processed: int = 0


# ---------------------------------------------------------------------------
# HistoricalGexService
# ---------------------------------------------------------------------------

class HistoricalGexService:
    """Calculate observed historical GEX from stored historical data.

    Reads from:
      - option_greeks (gamma, spot, strike, expiry, option_type)
      - option_candles (open_interest)
      - contract_specs (lot_size)

    Writes to:
      - historical_gex (observed GEX per option per timestamp)

    The service processes data in batches from the database rather than
    loading everything into memory.
    """

    def __init__(self, db: Session, calc_version: str = CALC_VERSION):
        self.db = db
        self.calc_version = calc_version

    # ------------------------------------------------------------------
    # Main calculation: single instrument
    # ------------------------------------------------------------------

    def calculate_instrument(self, instrument_key: str) -> list[OptionGexRow]:
        """Calculate observed GEX for all candles of one instrument.

        Returns a list of OptionGexRow (one per candle).
        """
        # Fetch Greeks (authoritative source for gamma, spot, strike, type)
        stmt_greeks = (
            select(OptionGreeks)
            .where(OptionGreeks.instrument_key == instrument_key)
            .where(OptionGreeks.status == "SUCCESS")
            .order_by(OptionGreeks.open_time)
        )
        greeks_rows = list(self.db.execute(stmt_greeks).scalars().all())
        if not greeks_rows:
            return []

        # Fetch OI from option_candles (keyed by instrument_key + open_time)
        stmt_candles = (
            select(OptionCandle)
            .where(OptionCandle.instrument_key == instrument_key)
            .order_by(OptionCandle.open_time)
        )
        candle_rows = list(self.db.execute(stmt_candles).scalars().all())
        # Build OI lookup by open_time
        oi_map = {}
        for c in candle_rows:
            oi_map[c.open_time] = c.open_interest

        results: list[OptionGexRow] = []
        for g in greeks_rows:
            oi = oi_map.get(g.open_time)

            exclusion = _validate_option_row(
                gamma=g.gamma,
                oi=oi,
                spot=g.spot,
                strike=g.strike,
                option_type=g.option_type,
            )

            if exclusion is not None:
                results.append(OptionGexRow(
                    instrument_key=g.instrument_key,
                    interval=g.interval,
                    open_time=g.open_time,
                    spot=g.spot or 0.0,
                    strike=g.strike or 0.0,
                    expiry=g.expiry,
                    option_type=g.option_type or "CE",
                    gamma=g.gamma or 0.0,
                    open_interest=oi or 0.0,
                    option_price=g.option_price or 0.0,
                    lot_size=g.lot_size,
                    raw_gex=0.0,
                    signed_gex=0.0,
                    status="EXCLUDED",
                    exclusion_reason=exclusion.value,
                ))
                continue

            raw = compute_raw_gex(g.gamma, oi, g.spot)
            signed = compute_signed_gex(g.option_type, raw)

            results.append(OptionGexRow(
                instrument_key=g.instrument_key,
                interval=g.interval,
                open_time=g.open_time,
                spot=g.spot,
                strike=g.strike,
                expiry=g.expiry,
                option_type=g.option_type,
                gamma=g.gamma,
                open_interest=oi,
                option_price=g.option_price,
                lot_size=g.lot_size,
                raw_gex=raw,
                signed_gex=signed,
                status="SUCCESS",
            ))

        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist_results(self, results: list[OptionGexRow]) -> int:
        """Persist GEX results via idempotent upsert.

        Returns the number of rows inserted/updated.
        """
        stored = 0
        for r in results:
            try:
                self.db.execute(
                    sqlite_insert(HistoricalGexSnapshot)
                    .values(
                        instrument_key=r.instrument_key,
                        interval=r.interval,
                        open_time=r.open_time,
                        spot=r.spot,
                        strike=r.strike,
                        expiry=r.expiry,
                        option_type=r.option_type,
                        gamma=r.gamma,
                        open_interest=r.open_interest,
                        option_price=r.option_price,
                        lot_size=r.lot_size,
                        raw_gex=r.raw_gex,
                        signed_gex=r.signed_gex,
                        calc_version=self.calc_version,
                        calculated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        status=r.status,
                        exclusion_reason=r.exclusion_reason,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            "instrument_key", "interval", "open_time", "calc_version",
                        ],
                        set_={
                            "spot": r.spot,
                            "strike": r.strike,
                            "expiry": r.expiry,
                            "option_type": r.option_type,
                            "gamma": r.gamma,
                            "open_interest": r.open_interest,
                            "option_price": r.option_price,
                            "lot_size": r.lot_size,
                            "raw_gex": r.raw_gex,
                            "signed_gex": r.signed_gex,
                            "calculated_at": datetime.now(timezone.utc).replace(tzinfo=None),
                            "status": r.status,
                            "exclusion_reason": r.exclusion_reason,
                        },
                    )
                )
                stored += 1
            except Exception as e:
                logger.warning("Failed to persist GEX for %s: %s", r.instrument_key, e)

        self.db.commit()
        return stored

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def run_instrument(self, instrument_key: str) -> dict:
        """Calculate + persist GEX for one instrument. Returns summary."""
        results = self.calculate_instrument(instrument_key)
        stored = self.persist_results(results)

        success = sum(1 for r in results if r.status == "SUCCESS")
        excluded = len(results) - success

        return {
            "instrument_key": instrument_key,
            "total_candles": len(results),
            "success": success,
            "excluded": excluded,
            "persisted": stored,
        }

    def run_batch(
        self,
        instrument_keys: list[str] | None = None,
        expiry: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """Calculate + persist GEX for multiple instruments.

        If instrument_keys is None, discovers all instruments with
        option_greeks rows. If expiry is provided, filters to that expiry.
        """
        if instrument_keys is None:
            stmt = (
                select(OptionGreeks.instrument_key)
                .distinct()
                .where(OptionGreeks.status == "SUCCESS")
            )
            if expiry:
                stmt = stmt.where(OptionGreeks.expiry == expiry)
            instrument_keys = list(self.db.execute(stmt).scalars().all())

        if limit:
            instrument_keys = instrument_keys[:limit]

        total_success = 0
        total_excluded = 0
        total_persisted = 0
        instrument_summaries = []

        for ik in instrument_keys:
            summary = self.run_instrument(ik)
            instrument_summaries.append(summary)
            total_success += summary["success"]
            total_excluded += summary["excluded"]
            total_persisted += summary["persisted"]

        return {
            "instruments_processed": len(instrument_keys),
            "total_candles": total_success + total_excluded,
            "total_success": total_success,
            "total_excluded": total_excluded,
            "total_persisted": total_persisted,
            "instruments": instrument_summaries,
        }

    # ------------------------------------------------------------------
    # Aggregation (pure functions, no persistence)
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_by_strike(rows: list[OptionGexRow]) -> dict[float, StrikeGex]:
        """Aggregate option-level GEX to strike-level.

        Returns {strike: StrikeGex}.
        """
        strike_map: dict[float, StrikeGex] = {}
        for r in rows:
            if r.status != "SUCCESS":
                continue
            if r.strike not in strike_map:
                strike_map[r.strike] = StrikeGex(strike=r.strike)
            sg = strike_map[r.strike]
            if r.option_type == "CE":
                sg.call_gex += r.signed_gex  # already positive
                sg.call_oi += r.open_interest
                sg.call_gamma += r.gamma
                sg.has_call = True
            elif r.option_type == "PE":
                sg.put_gex += r.signed_gex  # already negative
                sg.put_oi += r.open_interest
                sg.put_gamma += r.gamma
                sg.has_put = True
        # Compute net for each strike
        for sg in strike_map.values():
            if sg.has_call and sg.has_put:
                sg.net_gex = sg.call_gex + sg.put_gex
        return strike_map

    @staticmethod
    def aggregate_by_expiry(rows: list[OptionGexRow]) -> dict[str, ExpiryGex]:
        """Aggregate option-level GEX to expiry-level.

        Returns {expiry: ExpiryGex}.
        """
        expiry_map: dict[str, ExpiryGex] = {}
        for r in rows:
            if r.status != "SUCCESS":
                continue
            exp = r.expiry
            if exp not in expiry_map:
                expiry_map[exp] = ExpiryGex(expiry=exp)
            eg = expiry_map[exp]
            if r.option_type == "CE":
                eg.call_gex += r.signed_gex
            elif r.option_type == "PE":
                eg.put_gex += r.signed_gex
        # Count strikes per expiry
        strike_sets: dict[str, set] = {}
        for r in rows:
            if r.status != "SUCCESS":
                continue
            strike_sets.setdefault(r.expiry, set()).add(r.strike)
        for exp, eg in expiry_map.items():
            eg.total_strikes = len(strike_sets.get(exp, set()))
            # A strike is "valid" if it has at least one side
            eg.valid_strikes = eg.total_strikes  # simplified
            eg.net_gex = eg.call_gex + eg.put_gex
        return expiry_map

    @staticmethod
    def compute_chain_gex(rows: list[OptionGexRow], spot: float) -> ChainGex:
        """Compute full chain-level GEX from option-level rows.

        Returns a ChainGex with by_strike and by_expiry aggregations.
        """
        if not rows:
            return ChainGex(timestamp=datetime.min, spot=spot)

        timestamp = rows[0].open_time

        by_strike = HistoricalGexService.aggregate_by_strike(rows)
        by_expiry = HistoricalGexService.aggregate_by_expiry(rows)

        call_total = sum(r.signed_gex for r in rows if r.status == "SUCCESS" and r.option_type == "CE")
        put_total = sum(r.signed_gex for r in rows if r.status == "SUCCESS" and r.option_type == "PE")

        return ChainGex(
            timestamp=timestamp,
            spot=spot,
            call_gex=call_total,
            put_gex=put_total,
            net_gex=call_total + put_total,
            by_strike=by_strike,
            by_expiry=by_expiry,
        )

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current historical GEX status."""
        total = self.db.scalar(
            select(func.count(HistoricalGexSnapshot.id))
        ) or 0
        success = self.db.scalar(
            select(func.count(HistoricalGexSnapshot.id))
            .where(HistoricalGexSnapshot.status == "SUCCESS")
        ) or 0
        excluded = total - success
        instruments = self.db.scalar(
            select(func.count(func.distinct(HistoricalGexSnapshot.instrument_key)))
        ) or 0
        timestamps = self.db.scalar(
            select(func.count(func.distinct(HistoricalGexSnapshot.open_time)))
        ) or 0

        # Exclusion breakdown
        exclusion_rows = self.db.execute(
            select(
                HistoricalGexSnapshot.exclusion_reason,
                func.count(HistoricalGexSnapshot.id),
            )
            .where(HistoricalGexSnapshot.status == "EXCLUDED")
            .group_by(HistoricalGexSnapshot.exclusion_reason)
        ).fetchall()
        exclusion_breakdown = {r[0]: r[1] for r in exclusion_rows if r[0]}

        return {
            "total_rows": total,
            "success_rows": success,
            "excluded_rows": excluded,
            "instruments": instruments,
            "timestamps": timestamps,
            "exclusion_breakdown": exclusion_breakdown,
            "calc_version": self.calc_version,
        }
