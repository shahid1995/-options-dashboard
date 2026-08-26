"""Server-side Live GEX Calculation — Phase 8A.

Authoritative backend GEX calculation that produces numerically equivalent
results to the frontend ``gex.js`` (Phase 7.1) for identical input.

**Formula contract (Phase 7.1 — preserved exactly):**

    raw_gex = gamma × OI × spot² × 0.01
    CE → +raw_gex
    PE → −raw_gex

**Input contract:**

Accepts the canonical option-chain dict produced by the Upstox adapter's
``transform_chain()``::

    {
        "symbol": "NIFTY",
        "expiry_date": "2026-08-28",
        "underlying_spot_price": 24230.5,
        "chain": [
            {
                "strike": 24000,
                "call": {"gamma": 0.003, "oi": 12345, ...},
                "put":  {"gamma": 0.002, "oi": 8765,  ...},
            },
            ...
        ]
    }

**Design rules:**

- Stateless: input chain → output GEX. No global mutable state.
- No database writes (Phase 8B handles persistence).
- No broker calls. Pure computation on supplied data.
- Every exclusion is documented with a machine-readable reason.
- OI is in contracts (NOT lots). Lot size is NOT part of the formula.
- Gamma must be >= 0 and finite for a valid GEX calculation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — must match frontend gex.js exactly
# ---------------------------------------------------------------------------

GEX_METHOD_VERSION = "GEX_STANDARD_V1"
GEX_SIGN_CONVENTION = "NAIVE_DEALER_CONVENTION"
GEX_FORMULA = "gamma * oi * spot^2 * 0.01"
GEX_FACTOR = 0.01  # 1% move factor


# ---------------------------------------------------------------------------
# Status / exclusion enums
# ---------------------------------------------------------------------------

class GexStatus(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class ExclusionReason(str, Enum):
    INVALID_GAMMA = "INVALID_GAMMA"
    MISSING_GAMMA = "MISSING_GAMMA"
    NEGATIVE_GAMMA = "NEGATIVE_GAMMA"
    INVALID_OI = "INVALID_OI"
    MISSING_OI = "MISSING_OI"
    ZERO_OI = "ZERO_OI"
    INVALID_SPOT = "INVALID_SPOT"
    MISSING_SPOT = "MISSING_SPOT"
    NO_CHAIN_DATA = "NO_CHAIN_DATA"


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _is_positive_finite(v) -> bool:
    """Check whether a value is a valid positive finite number for GEX.

    Matches the frontend ``isPositiveFinite()`` exactly:
      - None/missing → False
      - 0 → False (OI=0 means no exposure)
      - negative → False
      - NaN/Infinity → False
    """
    if v is None:
        return False
    try:
        n = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(n) and n > 0


def _validate_option_inputs(gamma, oi, spot) -> Optional[str]:
    """Validate a single option side's inputs for GEX.

    Returns None if valid, or an exclusion-reason string if invalid.
    Matches the frontend ``validateOptionInput()`` exactly.
    """
    if not _is_positive_finite(gamma):
        if gamma is None:
            return ExclusionReason.MISSING_GAMMA.value
        try:
            g = float(gamma)
        except (TypeError, ValueError):
            return ExclusionReason.INVALID_GAMMA.value
        if not math.isfinite(g):
            return ExclusionReason.INVALID_GAMMA.value
        if g < 0:
            return ExclusionReason.NEGATIVE_GAMMA.value
        return ExclusionReason.INVALID_GAMMA.value
    if not _is_positive_finite(oi):
        if oi is None:
            return ExclusionReason.MISSING_OI.value
        try:
            o = float(oi)
        except (TypeError, ValueError):
            return ExclusionReason.INVALID_OI.value
        if o == 0:
            return ExclusionReason.ZERO_OI.value
        return ExclusionReason.INVALID_OI.value
    # spot is validated at chain level, not per-option
    return None


# ---------------------------------------------------------------------------
# Core GEX calculation
# ---------------------------------------------------------------------------

def _raw_gex(gamma: float, oi: float, spot: float) -> float:
    """Compute raw GEX for one option.

    Formula: gamma × OI × spot² × 0.01

    OI is in NUMBER OF CONTRACTS (not lots). Lot size is NOT part of the
    formula because Upstox OI already represents contracts.
    """
    return gamma * oi * spot * spot * GEX_FACTOR


def _signed_gex(option_type: str, gamma: float, oi: float, spot: float) -> float:
    """Compute signed GEX for one option.

    Under NAIVE_DEALER_CONVENTION:
      Call GEX = + raw_gex
      Put GEX  = - raw_gex
    """
    raw = _raw_gex(gamma, oi, spot)
    return raw if option_type == "call" else -raw


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrikeGexResult:
    """GEX result for a single strike across call and put sides."""
    strike: float
    call_gex: Optional[float] = None
    put_gex: Optional[float] = None
    net_gex: Optional[float] = None
    call_oi: Optional[float] = None
    put_oi: Optional[float] = None
    call_gamma: Optional[float] = None
    put_gamma: Optional[float] = None
    status: str = GexStatus.UNAVAILABLE.value

    def to_dict(self) -> dict:
        return {
            "strike": self.strike,
            "callGex": self.call_gex,
            "putGex": self.put_gex,
            "netGex": self.net_gex,
            "callOi": self.call_oi,
            "putOi": self.put_oi,
            "callGamma": self.call_gamma,
            "putGamma": self.put_gamma,
            "status": self.status,
        }


@dataclass
class GexCalculationResult:
    """Complete GEX calculation result for an option chain."""
    symbol: Optional[str] = None
    spot: Optional[float] = None
    expiry: Optional[str] = None
    captured_at: str = ""
    methodology: str = GEX_METHOD_VERSION
    sign_convention: str = GEX_SIGN_CONVENTION
    call_gex: Optional[float] = None
    put_gex: Optional[float] = None
    net_gex: Optional[float] = None
    availability_status: str = GexStatus.UNAVAILABLE.value
    valid_strike_count: int = 0
    total_strike_count: int = 0
    strikes: list = field(default_factory=list)
    chain_age_ms: Optional[float] = None
    methodology_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "expiry": self.expiry,
            "captured_at": self.captured_at,
            "methodology": self.methodology,
            "sign_convention": self.sign_convention,
            "call_gex": self.call_gex,
            "put_gex": self.put_gex,
            "net_gex": self.net_gex,
            "availability_status": self.availability_status,
            "valid_strike_count": self.valid_strike_count,
            "total_strike_count": self.total_strike_count,
            "chain_age_ms": self.chain_age_ms,
            "methodology_metadata": self.methodology_metadata,
            "strikes": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.strikes],
        }


# ---------------------------------------------------------------------------
# LiveGexService
# ---------------------------------------------------------------------------

class LiveGexService:
    """Authoritative server-side GEX calculation.

    Stateless: input chain → output GEX. No global state, no database,
    no broker calls. Designed for multi-user safety — each request
    carries its own chain data.

    Usage::

        service = LiveGexService()
        result = service.calculate(chain_data)
    """

    def calculate(self, chain: dict) -> GexCalculationResult:
        """Calculate GEX from a canonical option chain.

        Args:
            chain: Canonical chain dict from Upstox adapter's ``transform_chain()``.
                   Must contain: symbol, expiry_date, underlying_spot_price, chain[].

        Returns:
            GexCalculationResult with chain-level and strike-level GEX.
        """
        now = datetime.now(timezone.utc)

        # Validate chain-level inputs
        spot = chain.get("underlying_spot_price") if chain else None
        symbol = chain.get("symbol") if chain else None
        expiry = chain.get("expiry_date") if chain else None
        chain_rows = chain.get("chain") if chain else None

        # Invalid spot → entire result unavailable
        if not _is_positive_finite(spot):
            return GexCalculationResult(
                symbol=symbol,
                spot=spot if isinstance(spot, (int, float)) else None,
                expiry=expiry,
                captured_at=now.isoformat(),
                availability_status=GexStatus.UNAVAILABLE.value,
                methodology_metadata=self._metadata(),
            )

        # Empty chain → unavailable
        if not chain_rows or len(chain_rows) == 0:
            return GexCalculationResult(
                symbol=symbol,
                spot=spot,
                expiry=expiry,
                captured_at=now.isoformat(),
                availability_status=GexStatus.UNAVAILABLE.value,
                methodology_metadata=self._metadata(),
            )

        # Calculate per-strike GEX
        strike_results = []
        call_total = 0.0
        put_total = 0.0
        has_call = False
        has_put = False
        available_count = 0
        partial_count = 0
        invalid_count = 0

        for row in chain_rows:
            sr = self._calculate_strike_gex(row, spot)
            strike_results.append(sr)

            if sr.call_gex is not None:
                call_total += sr.call_gex
                has_call = True
            if sr.put_gex is not None:
                put_total += sr.put_gex
                has_put = True

            if sr.status == GexStatus.AVAILABLE.value:
                available_count += 1
            elif sr.status == GexStatus.PARTIAL.value:
                partial_count += 1
            elif sr.status == GexStatus.INVALID.value:
                invalid_count += 1

        # Determine chain-level availability status
        # Matches frontend expiryGex() logic exactly
        if available_count == len(strike_results) and available_count > 0:
            availability_status = GexStatus.AVAILABLE.value
        elif available_count + partial_count > 0:
            availability_status = GexStatus.PARTIAL.value
        elif invalid_count > 0:
            availability_status = GexStatus.INVALID.value
        else:
            availability_status = GexStatus.UNAVAILABLE.value

        # Chain-level GEX totals
        call_gex = call_total if has_call else None
        put_gex = put_total if has_put else None
        net_gex = (call_total + put_total) if (has_call and has_put) else None

        # Chain age (ms since earliest quote_timestamp)
        chain_age_ms = self._compute_chain_age(chain_rows)

        return GexCalculationResult(
            symbol=symbol,
            spot=spot,
            expiry=expiry,
            captured_at=now.isoformat(),
            methodology=GEX_METHOD_VERSION,
            sign_convention=GEX_SIGN_CONVENTION,
            call_gex=call_gex,
            put_gex=put_gex,
            net_gex=net_gex,
            availability_status=availability_status,
            valid_strike_count=available_count + partial_count,
            total_strike_count=len(strike_results),
            strikes=strike_results,
            chain_age_ms=chain_age_ms,
            methodology_metadata=self._metadata(),
        )

    def _calculate_strike_gex(self, row: dict, spot: float) -> StrikeGexResult:
        """Calculate GEX for a single strike across call and put sides.

        Matches the frontend ``strikeGex()`` logic exactly.
        """
        strike = row.get("strike")
        call = row.get("call") or {}
        put = row.get("put") or {}

        call_gamma = call.get("gamma")
        call_oi = call.get("oi")
        put_gamma = put.get("gamma")
        put_oi = put.get("oi")

        # Validate each side independently
        call_error = _validate_option_inputs(call_gamma, call_oi, spot)
        put_error = _validate_option_inputs(put_gamma, put_oi, spot)

        call_gex = None
        put_gex = None
        net_gex = None
        status: str

        if call_error is None and put_error is None:
            # Both sides available
            call_gex = _signed_gex("call", float(call_gamma), float(call_oi), spot)
            put_gex = _signed_gex("put", float(put_gamma), float(put_oi), spot)
            net_gex = call_gex + put_gex
            status = GexStatus.AVAILABLE.value
        elif call_error is None:
            # Only call side available
            call_gex = _signed_gex("call", float(call_gamma), float(call_oi), spot)
            status = GexStatus.PARTIAL.value
        elif put_error is None:
            # Only put side available
            put_gex = _signed_gex("put", float(put_gamma), float(put_oi), spot)
            status = GexStatus.PARTIAL.value
        else:
            # Neither side available
            # Match frontend: INVALID if either side has invalid gamma
            if call_error == ExclusionReason.INVALID_GAMMA.value or \
               put_error == ExclusionReason.INVALID_GAMMA.value or \
               call_error == ExclusionReason.NEGATIVE_GAMMA.value or \
               put_error == ExclusionReason.NEGATIVE_GAMMA.value:
                status = GexStatus.INVALID.value
            else:
                status = GexStatus.UNAVAILABLE.value

        return StrikeGexResult(
            strike=strike,
            call_gex=call_gex,
            put_gex=put_gex,
            net_gex=net_gex,
            call_oi=call_oi,
            put_oi=put_oi,
            call_gamma=call_gamma,
            put_gamma=put_gamma,
            status=status,
        )

    def _compute_chain_age(self, chain_rows: list) -> Optional[float]:
        """Compute chain age in milliseconds since the earliest quote timestamp.

        Matches the frontend ``_computeChainAge()`` logic.
        """
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        earliest_ms = None

        for row in chain_rows:
            for side in ("call", "put"):
                ts_str = (row.get(side) or {}).get("quote_timestamp")
                if ts_str:
                    try:
                        # Handle ISO format with or without timezone
                        ts_str_clean = ts_str.replace("Z", "+00:00")
                        if "+" not in ts_str_clean and "-" not in ts_str_clean[10:]:
                            ts_str_clean += "+00:00"
                        ts_ms = datetime.fromisoformat(ts_str_clean).timestamp() * 1000
                        if earliest_ms is None or ts_ms < earliest_ms:
                            earliest_ms = ts_ms
                    except (ValueError, TypeError):
                        pass

        if earliest_ms is not None:
            return max(0.0, now_ms - earliest_ms)
        return None

    @staticmethod
    def _metadata() -> dict:
        """Methodology metadata — matches frontend ``methodologyMetadata``."""
        return {
            "gexVersion": GEX_METHOD_VERSION,
            "formula": GEX_FORMULA,
            "oiUnit": "contracts",
            "signConvention": GEX_SIGN_CONVENTION,
            "callSign": 1,
            "putSign": -1,
            "lotSizeFactorApplied": False,
            "engine": "LiveGexService_v1",
        }
