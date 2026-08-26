"""Historical Greeks reconstruction engine — Phase 7.19B.

Computes IV + Black-Scholes Greeks from raw historical option candles,
contract metadata, and NIFTY index candles.

Three-layer architecture:
  RAW (immutable):   option_candles + nifty_candles + contract_specs
  MODEL (derived):   option_greeks  (this module)
  ANALYTICS:         GEX / Vega / Delta / IV research

Key properties:
  - **Deterministic**: same inputs always produce the same Greeks.
  - **Idempotent**: re-running the same calc_version does not create duplicates.
  - **Versioned**: different calc_version values coexist for model comparison.
  - **Safe**: one bad candle never aborts a batch.
  - **Raw-immutable**: never modifies option_candles / nifty_candles / contract_specs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import OptionCandle, ContractSpec, NiftyCandle, OptionGreeks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RISK_FREE_RATE = 0.065       # 6.5% — Indian government bond proxy
DEFAULT_CALC_VERSION = "1.0.0"
DEFAULT_CALC_MODEL = "BLACK_SCHOLES_EUROPEAN"

# IV solver bounds
IV_MIN = 0.001    # 0.1%
IV_MAX = 10.0     # 1000%
IV_BRACKET_LOW = 0.01
IV_BRACKET_HIGH = 5.0
IV_TOLERANCE = 1e-8
IV_MAX_ITER = 100

# Math constants
_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Calculation status
# ---------------------------------------------------------------------------

class CalcStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_IV = "NO_IV"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_PRICE = "INVALID_PRICE"
    BELOW_INTRINSIC = "BELOW_INTRINSIC"
    ABOVE_THEORETICAL_MAX = "ABOVE_THEORETICAL_MAX"
    EXPIRED = "EXPIRED"
    NUMERICAL_ERROR = "NUMERICAL_ERROR"
    NO_BRACKET = "NO_BRACKET"
    CONVERGENCE_FAILED = "CONVERGENCE_FAILED"


# ---------------------------------------------------------------------------
# Black-Scholes math (pure functions, no side effects)
# ---------------------------------------------------------------------------

def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via error function."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def bs_price(
    option_type: str,
    S: float,
    K: float,
    T: float,
    sigma: float,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = 0.0,
) -> float:
    """Black-Scholes European option price.

    Parameters
    ----------
    option_type : "CE" or "PE"
    S : spot price
    K : strike price
    T : time to expiry in year fractions
    sigma : volatility (decimal, e.g. 0.18 = 18%)
    r : risk-free rate (decimal, continuously compounded)
    q : dividend yield (0 for NIFTY index options)
    """
    if T <= 0:
        if option_type == "CE":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        fwd = S * math.exp((r - q) * T)
        if option_type == "CE":
            return max(fwd - K, 0.0) * math.exp(-r * T)
        return max(K - fwd, 0.0) * math.exp(-r * T)

    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    dfQ = math.exp(-q * T)
    dfR = math.exp(-r * T)
    nD1 = _norm_cdf(d1)
    nD2 = _norm_cdf(d2)

    if option_type == "CE":
        return S * dfQ * nD1 - K * dfR * nD2
    else:
        return K * dfR * _norm_cdf(-d2) - S * dfQ * _norm_cdf(-d1)


def bs_greeks(
    option_type: str,
    S: float,
    K: float,
    T: float,
    sigma: float,
    r: float = DEFAULT_RISK_FREE_RATE,
    q: float = 0.0,
) -> dict[str, float]:
    """Black-Scholes per-unit Greeks.

    Returns delta, gamma, vega (per 1.00 vol fraction), theta (annualized).
    All values are per-unit — not scaled by lot_size.
    """
    if T <= 0:
        if option_type == "CE":
            return {"delta": 1.0 if S > K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        return {"delta": -1.0 if S < K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    if sigma <= 0:
        fwd = S * math.exp((r - q) * T)
        if option_type == "CE":
            return {"delta": 1.0 if fwd > K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        return {"delta": -1.0 if fwd < K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}

    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    pdf = _norm_pdf(d1)
    dfQ = math.exp(-q * T)
    dfR = math.exp(-r * T)
    nD1 = _norm_cdf(d1)
    is_call = option_type == "CE"

    delta = dfQ * (nD1 if is_call else nD1 - 1.0)
    gamma = (dfQ * pdf) / (S * sigma * sqrtT)
    vega = S * dfQ * pdf * sqrtT

    theta = (
        -(S * dfQ * pdf * sigma) / (2 * sqrtT)
        + (-1 if is_call else 1) * r * K * dfR * (_norm_cdf(d2) if is_call else _norm_cdf(-d2))
        + (1 if is_call else -1) * q * S * dfQ * (nD1 if is_call else _norm_cdf(-d1))
    )

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def bs_intrinsic(option_type: str, S: float, K: float) -> float:
    """European option intrinsic value."""
    if option_type == "CE":
        return max(S - K, 0.0)
    return max(K - S, 0.0)


# ---------------------------------------------------------------------------
# IV solver (bisection, robust)
# ---------------------------------------------------------------------------

def solve_iv(
    option_type: str,
    S: float,
    K: float,
    T: float,
    market_price: float,
    r: float = DEFAULT_RISK_FREE_RATE,
) -> tuple[Optional[float], Optional[str]]:
    """Solve for implied volatility using bisection.

    Returns (iv, error_code).  error_code is None on success.
    iv is in decimal form (0.18 = 18%).
    """
    if T <= 0:
        return (None, CalcStatus.EXPIRED.value)
    if S <= 0:
        return (None, CalcStatus.INVALID_PRICE.value)
    if K <= 0:
        return (None, CalcStatus.INVALID_PRICE.value)
    if market_price <= 0:
        return (None, CalcStatus.INVALID_PRICE.value)

    intrinsic = bs_intrinsic(option_type, S, K)
    if market_price < intrinsic - 1e-10:
        return (None, CalcStatus.BELOW_INTRINSIC.value)

    # Price upper bound
    if option_type == "CE":
        upper = S * math.exp(-0.0 * T)  # q=0
    else:
        upper = K * math.exp(-r * T)
    if market_price > upper + 1e-10:
        return (None, CalcStatus.ABOVE_THEORETICAL_MAX.value)

    # If price == intrinsic exactly, IV is effectively 0
    if abs(market_price - intrinsic) < 1e-10:
        return (IV_MIN, None)

    sigma_low = IV_MIN
    sigma_high = IV_MAX
    f_low = bs_price(option_type, S, K, T, sigma_low, r) - market_price
    f_high = bs_price(option_type, S, K, T, sigma_high, r) - market_price

    if f_low * f_high > 0:
        return (None, CalcStatus.NO_BRACKET.value)

    for _ in range(IV_MAX_ITER):
        sigma_mid = (sigma_low + sigma_high) / 2.0
        f_mid = bs_price(option_type, S, K, T, sigma_mid, r) - market_price

        if abs(f_mid) < IV_TOLERANCE or (sigma_high - sigma_low) / 2.0 < IV_TOLERANCE:
            return (sigma_mid, None)

        if f_low * f_mid < 0:
            sigma_high = sigma_mid
            f_high = f_mid
        else:
            sigma_low = sigma_mid
            f_low = f_mid

    return ((sigma_low + sigma_high) / 2.0, CalcStatus.CONVERGENCE_FAILED.value)


# ---------------------------------------------------------------------------
# Time-to-expiry
# ---------------------------------------------------------------------------

def compute_time_to_expiry(valuation_utc: datetime, expiry_date_str: str) -> float:
    """Compute T in year fractions (calendar days / 365.25).

    The expiry reference is 15:30 IST = 10:00 UTC on the expiry date.
    Handles both naive and aware datetimes for valuation_utc.
    """
    expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
    # Expiry time reference: 15:30 IST = 10:00 UTC (settlement reference)
    expiry_naive = expiry_date.replace(hour=10, minute=0)
    # Ensure both datetimes are naive for comparison
    val_naive = valuation_utc.replace(tzinfo=None) if valuation_utc.tzinfo else valuation_utc
    delta = expiry_naive - val_naive
    return max(0.0, delta.total_seconds() / (365.25 * 86400))


# ---------------------------------------------------------------------------
# Spot alignment
# ---------------------------------------------------------------------------

def align_spot(
    option_open_time_utc: datetime,
    nifty_candles_sorted: list[dict],
) -> Optional[float]:
    """Find the NIFTY close price aligned to an option candle timestamp.

    Uses the latest NIFTY candle whose open_time <= option_open_time.
    This correctly handles:
      - Exact matches (most option candles during trading hours)
      - Post-close option candles (15:27-15:40 IST) → use last index candle
      - Missing data → return None

    Parameters
    ----------
    option_open_time_utc : datetime (UTC, naive or aware)
    nifty_candles_sorted : list of dicts with 'open_time' and 'close',
                           sorted ascending by open_time
    """
    candidate = None
    for candle in nifty_candles_sorted:
        ct = candle["open_time"]
        if ct <= option_open_time_utc:
            cl = candle.get("close")
            if cl is not None and cl > 0:
                candidate = cl
        else:
            break
    return candidate


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GreeksResult:
    """Result of a single Greek calculation."""
    instrument_key: str
    interval: str
    open_time: datetime
    spot: float
    strike: float
    expiry: str
    option_type: str
    option_price: float
    lot_size: Optional[int]
    time_to_expiry: float
    risk_free_rate: float
    intrinsic_value: float
    implied_volatility: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    vega: Optional[float]
    theta: Option[float]
    calc_version: str
    status: str
    error_code: Optional[str]


# ---------------------------------------------------------------------------
# Core calculation function (pure)
# ---------------------------------------------------------------------------

def calculate_greeks_for_candle(
    option_type: str,
    S: float,
    K: float,
    T: float,
    market_price: float,
    r: float = DEFAULT_RISK_FREE_RATE,
    calc_version: str = DEFAULT_CALC_VERSION,
) -> GreeksResult:
    """Calculate IV + Greeks for one option candle.

    This is a pure function — no database access.
    Returns a fully populated GreeksResult (either SUCCESS or error status).
    """
    intrinsic = bs_intrinsic(option_type, S, K)

    # Zero/negative price — short-circuit
    if market_price <= 0:
        return GreeksResult(
            instrument_key="", interval="", open_time=datetime.min,
            spot=S, strike=K, expiry="", option_type=option_type,
            option_price=market_price, lot_size=None,
            time_to_expiry=T, risk_free_rate=r, intrinsic_value=intrinsic,
            implied_volatility=None, delta=None, gamma=None, vega=None, theta=None,
            calc_version=calc_version, status=CalcStatus.INVALID_PRICE.value,
            error_code="ZERO_PRICE",
        )

    # Expired option — directional delta, no IV
    if T <= 0:
        if option_type == "CE":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return GreeksResult(
            instrument_key="", interval="", open_time=datetime.min,
            spot=S, strike=K, expiry="", option_type=option_type,
            option_price=market_price, lot_size=None,
            time_to_expiry=0.0, risk_free_rate=r, intrinsic_value=intrinsic,
            implied_volatility=None,
            delta=delta, gamma=0.0, vega=0.0, theta=0.0,
            calc_version=calc_version,
            status=CalcStatus.SUCCESS.value, error_code=None,
        )

    # Solve IV
    iv, error_code = solve_iv(option_type, S, K, T, market_price, r)

    if iv is None:
        return GreeksResult(
            instrument_key="", interval="", open_time=datetime.min,
            spot=S, strike=K, expiry="", option_type=option_type,
            option_price=market_price, lot_size=None,
            time_to_expiry=T, risk_free_rate=r, intrinsic_value=intrinsic,
            implied_volatility=None, delta=None, gamma=None, vega=None, theta=None,
            calc_version=calc_version, status=CalcStatus.NO_IV.value,
            error_code=error_code,
        )

    # Calculate Greeks from IV
    try:
        g = bs_greeks(option_type, S, K, T, iv, r)
    except (ValueError, ZeroDivisionError):
        return GreeksResult(
            instrument_key="", interval="", open_time=datetime.min,
            spot=S, strike=K, expiry="", option_type=option_type,
            option_price=market_price, lot_size=None,
            time_to_expiry=T, risk_free_rate=r, intrinsic_value=intrinsic,
            implied_volatility=iv, delta=None, gamma=None, vega=None, theta=None,
            calc_version=calc_version, status=CalcStatus.NUMERICAL_ERROR.value,
            error_code="GREEK_CALC_FAILED",
        )

    return GreeksResult(
        instrument_key="", interval="", open_time=datetime.min,
        spot=S, strike=K, expiry="", option_type=option_type,
        option_price=market_price, lot_size=None,
        time_to_expiry=T, risk_free_rate=r, intrinsic_value=intrinsic,
        implied_volatility=iv,
        delta=g["delta"], gamma=g["gamma"], vega=g["vega"], theta=g["theta"],
        calc_version=calc_version,
        status=CalcStatus.SUCCESS.value, error_code=None,
    )


# ---------------------------------------------------------------------------
# Batch engine (database-aware)
# ---------------------------------------------------------------------------

class HistoricalGreeksEngine:
    """Batch Greeks reconstruction engine.

    Loads raw data from the database, calculates Greeks for each candle,
    and persists results.  Handles caching, error isolation, and
    idempotent upsert.
    """

    def __init__(
        self,
        db: Session,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        calc_version: str = DEFAULT_CALC_VERSION,
    ):
        self.db = db
        self.r = risk_free_rate
        self.calc_version = calc_version

        # Caches (populated per-batch)
        self._spec_cache: dict[str, dict] = {}
        self._index_cache: dict[str, list[dict]] = {}  # date → sorted candles

    def _get_spec(self, instrument_key: str) -> Optional[dict]:
        """Load and cache contract spec by instrument_key."""
        if instrument_key in self._spec_cache:
            return self._spec_cache[instrument_key]
        row = self.db.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == instrument_key)
        ).scalar_one_or_none()
        if row is None:
            self._spec_cache[instrument_key] = None
            return None
        spec = {
            "instrument_key": row.instrument_key,
            "expiry": row.expiry,
            "strike_price": row.strike_price,
            "instrument_type": row.instrument_type,
            "lot_size": row.lot_size,
            "underlying": row.underlying,
        }
        self._spec_cache[instrument_key] = spec
        return spec

    def _get_index_candles(self, date_str: str) -> list[dict]:
        """Load and cache NIFTY index candles for a date, sorted ascending.

        Phase 7.24.4: Both nifty_candles and option_candles store timestamps
        as naive IST (09:15-15:27 for NIFTY, 09:15-15:39 for options).
        No timezone conversion is needed for alignment.
        """
        if date_str in self._index_cache:
            return self._index_cache[date_str]

        target = datetime.strptime(date_str, "%Y-%m-%d").date()

        # NIFTY candles are stored in IST: 09:15 to ~15:27
        day_start = datetime(target.year, target.month, target.day, 9, 15)
        day_end = datetime(target.year, target.month, target.day, 15, 30)

        rows = self.db.execute(
            select(NiftyCandle)
            .where(NiftyCandle.symbol == "NIFTY")
            .where(NiftyCandle.interval == "3min")
            .where(NiftyCandle.open_time >= day_start)
            .where(NiftyCandle.open_time <= day_end)
            .order_by(NiftyCandle.open_time.asc())
        ).scalars().all()

        candles = [
            {"open_time": r.open_time, "close": r.close}
            for r in rows
        ]
        self._index_cache[date_str] = candles
        return candles

    def calculate_instrument(
        self,
        instrument_key: str,
    ) -> list[GreeksResult]:
        """Calculate Greeks for all candles of one instrument.

        Returns a list of GreeksResult, one per candle.
        Failed candles get explicit error statuses — never aborts.
        """
        spec = self._get_spec(instrument_key)
        if spec is None:
            return []

        # Load option candles
        rows = self.db.execute(
            select(OptionCandle)
            .where(OptionCandle.instrument_key == instrument_key)
            .order_by(OptionCandle.open_time.asc())
        ).scalars().all()

        if not rows:
            return []

        expiry = spec["expiry"]
        K = spec["strike_price"]
        option_type = spec["instrument_type"]
        lot_size = spec.get("lot_size")

        results: list[GreeksResult] = []

        for row in rows:
            result = self._calculate_single(
                row, spec, expiry, K, option_type, lot_size,
            )
            results.append(result)

        return results

    def _calculate_single(
        self,
        candle: OptionCandle,
        spec: dict,
        expiry: str,
        K: float,
        option_type: str,
        lot_size: Optional[int],
    ) -> GreeksResult:
        """Calculate Greeks for a single option candle."""
        S = candle.close  # option price (the option's market price)
        open_time = candle.open_time

        # Phase 7.24.4: Both option_candles and nifty_candles now store
        # timestamps as naive IST. No conversion needed for alignment.
        # Get index candles for this date.
        date_str = open_time.strftime("%Y-%m-%d")
        index_candles = self._get_index_candles(date_str)

        # Align spot (both timestamps are naive IST)
        spot = align_spot(open_time, index_candles)
        if spot is None:
            return self._error_result(
                candle, spec, CalcStatus.INSUFFICIENT_DATA, "NO_SPOT"
            )

        # Time to expiry
        T = compute_time_to_expiry(open_time, expiry)

        intrinsic = bs_intrinsic(option_type, spot, K)

        # Validate option price
        if S <= 0:
            return GreeksResult(
                instrument_key=candle.instrument_key,
                interval=candle.interval,
                open_time=open_time,
                spot=spot, strike=K, expiry=expiry,
                option_type=option_type, option_price=S,
                lot_size=lot_size,
                time_to_expiry=T,
                risk_free_rate=self.r,
                intrinsic_value=intrinsic,
                implied_volatility=None,
                delta=None, gamma=None, vega=None, theta=None,
                calc_version=self.calc_version,
                status=CalcStatus.INVALID_PRICE.value,
                error_code="ZERO_PRICE",
            )

        # Expired option
        if T <= 0:
            if option_type == "CE":
                delta = 1.0 if spot > K else 0.0
            else:
                delta = -1.0 if spot < K else 0.0
            return GreeksResult(
                instrument_key=candle.instrument_key,
                interval=candle.interval,
                open_time=open_time,
                spot=spot, strike=K, expiry=expiry,
                option_type=option_type, option_price=S,
                lot_size=lot_size,
                time_to_expiry=0.0,
                risk_free_rate=self.r,
                intrinsic_value=intrinsic,
                implied_volatility=None,
                delta=delta, gamma=0.0, vega=0.0, theta=0.0,
                calc_version=self.calc_version,
                status=CalcStatus.SUCCESS.value,
                error_code=None,
            )

        # Solve IV + Greeks
        result = calculate_greeks_for_candle(
            option_type, spot, K, T, S, self.r, self.calc_version,
        )

        # Fill in identity fields
        result.instrument_key = candle.instrument_key
        result.interval = candle.interval
        result.open_time = open_time
        result.expiry = expiry
        result.lot_size = lot_size
        result.spot = spot
        result.intrinsic_value = intrinsic

        return result

    def _error_result(
        self,
        candle: OptionCandle,
        spec: dict,
        status: CalcStatus,
        error_code: str,
    ) -> GreeksResult:
        """Create an error-status result for a candle."""
        return GreeksResult(
            instrument_key=candle.instrument_key,
            interval=candle.interval,
            open_time=candle.open_time,
            spot=0.0,
            strike=spec["strike_price"],
            expiry=spec["expiry"],
            option_type=spec["instrument_type"],
            option_price=candle.close,
            lot_size=spec.get("lot_size"),
            time_to_expiry=0.0,
            risk_free_rate=self.r,
            intrinsic_value=0.0,
            implied_volatility=None,
            delta=None, gamma=None, vega=None, theta=None,
            calc_version=self.calc_version,
            status=status.value,
            error_code=error_code,
        )

    def persist_results(self, results: list[GreeksResult]) -> int:
        """Persist calculation results via idempotent upsert.

        Returns the number of rows inserted/updated.
        """
        stored = 0
        for r in results:
            try:
                self.db.execute(
                    sqlite_insert(OptionGreeks)
                    .values(
                        instrument_key=r.instrument_key,
                        interval=r.interval,
                        open_time=r.open_time,
                        spot=r.spot,
                        strike=r.strike,
                        expiry=r.expiry,
                        option_type=r.option_type,
                        option_price=r.option_price,
                        lot_size=r.lot_size,
                        time_to_expiry=r.time_to_expiry,
                        risk_free_rate=r.risk_free_rate,
                        intrinsic_value=r.intrinsic_value,
                        implied_volatility=r.implied_volatility,
                        delta=r.delta,
                        gamma=r.gamma,
                        vega=r.vega,
                        theta=r.theta,
                        calc_model=DEFAULT_CALC_MODEL,
                        calc_version=r.calc_version,
                        calculated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        status=r.status,
                        error_code=r.error_code,
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
                            "option_price": r.option_price,
                            "lot_size": r.lot_size,
                            "time_to_expiry": r.time_to_expiry,
                            "risk_free_rate": r.risk_free_rate,
                            "intrinsic_value": r.intrinsic_value,
                            "implied_volatility": r.implied_volatility,
                            "delta": r.delta,
                            "gamma": r.gamma,
                            "vega": r.vega,
                            "theta": r.theta,
                            "calc_model": DEFAULT_CALC_MODEL,
                            "calculated_at": datetime.now(timezone.utc).replace(tzinfo=None),
                            "status": r.status,
                            "error_code": r.error_code,
                        },
                    )
                )
                stored += 1
            except Exception as e:
                logger.warning("Failed to persist greeks for %s: %s", r.instrument_key, e)

        self.db.commit()
        return stored

    def run_instrument(self, instrument_key: str) -> dict:
        """Calculate + persist Greeks for one instrument.

        Returns a summary dict.
        """
        results = self.calculate_instrument(instrument_key)
        stored = self.persist_results(results)

        success = sum(1 for r in results if r.status == CalcStatus.SUCCESS.value)
        failed = len(results) - success

        return {
            "instrument_key": instrument_key,
            "total_candles": len(results),
            "success": success,
            "failed": failed,
            "persisted": stored,
            "lot_size": results[0].lot_size if results else None,
        }

    def run_batch(
        self,
        instrument_keys: list[str] | None = None,
        expiry: str | None = None,
    ) -> dict:
        """Calculate + persist Greeks for multiple instruments.

        If instrument_keys is None, discovers from option_candles table.
        If expiry is provided, filters to that expiry.
        """
        if instrument_keys is None:
            stmt = select(OptionCandle.instrument_key).distinct()
            if expiry:
                # Filter by expiry through contract_specs join
                stmt = (
                    select(OptionCandle.instrument_key)
                    .distinct()
                    .join(ContractSpec, ContractSpec.instrument_key == OptionCandle.instrument_key)
                    .where(ContractSpec.expiry == expiry)
                )
            instrument_keys = list(self.db.execute(stmt).scalars().all())

        total_success = 0
        total_failed = 0
        total_persisted = 0
        instrument_summaries = []

        for ik in instrument_keys:
            summary = self.run_instrument(ik)
            instrument_summaries.append(summary)
            total_success += summary["success"]
            total_failed += summary["failed"]
            total_persisted += summary["persisted"]

        return {
            "instruments_processed": len(instrument_keys),
            "total_candles": total_success + total_failed,
            "total_success": total_success,
            "total_failed": total_failed,
            "total_persisted": total_persisted,
            "instruments": instrument_summaries,
        }
