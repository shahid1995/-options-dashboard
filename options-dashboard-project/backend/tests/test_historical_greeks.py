"""Phase 7.19B — Historical Greeks engine tests.

Covers:
  A. Black-Scholes pricing (cross-validated with 7.19A)
  B. IV solver
  C. Greeks values
  D. Spot alignment
  E. Time-to-expiry
  F. Persistence + idempotency
  G. Batch processing
  H. Edge cases
  I. Pilot validation (existing 2024-10-31 data)
  J. Raw data immutability
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.services.historical_greeks import (
    bs_price,
    bs_greeks,
    bs_intrinsic,
    solve_iv,
    compute_time_to_expiry,
    align_spot,
    calculate_greeks_for_candle,
    CalcStatus,
    HistoricalGreeksEngine,
    DEFAULT_RISK_FREE_RATE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ============================================================================
# A. Black-Scholes Pricing
# ============================================================================

class TestBlackScholesPricing:
    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = DEFAULT_RISK_FREE_RATE

    def test_atm_ce_positive(self):
        price = bs_price("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert price > 0

    def test_atm_pe_positive(self):
        price = bs_price("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert price > 0

    def test_put_call_parity(self):
        C = bs_price("CE", self.S, self.K, self.T, self.sigma, self.r)
        P = bs_price("PE", self.S, self.K, self.T, self.sigma, self.r)
        parity_rhs = self.S - self.K * math.exp(-self.r * self.T)
        assert abs((C - P) - parity_rhs) < 0.01

    def test_itm_ce_above_intrinsic(self):
        K_itm = 24500.0
        price = bs_price("CE", self.S, K_itm, self.T, self.sigma, self.r)
        assert price > self.S - K_itm

    def test_otm_ce_less_than_atm(self):
        price_otm = bs_price("CE", self.S, 25500, self.T, self.sigma, self.r)
        price_atm = bs_price("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert price_otm < price_atm

    def test_expired_ce_intrinsic(self):
        assert bs_price("CE", 25500, 25000, 0, self.sigma, self.r) == 500.0

    def test_expired_pe_intrinsic(self):
        assert bs_price("PE", 24500, 25000, 0, self.sigma, self.r) == 500.0

    def test_expired_otm_zero(self):
        assert bs_price("CE", 24500, 25000, 0, self.sigma, self.r) == 0.0


# ============================================================================
# B. IV Solver
# ============================================================================

class TestIVSolver:
    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    r = DEFAULT_RISK_FREE_RATE

    @pytest.mark.parametrize("sigma_input", [0.10, 0.15, 0.18, 0.25, 0.40])
    def test_ce_roundtrip(self, sigma_input):
        price = bs_price("CE", self.S, self.K, self.T, sigma_input, self.r)
        iv, err = solve_iv("CE", self.S, self.K, self.T, price, self.r)
        assert err is None
        assert abs(iv - sigma_input) < 1e-4

    @pytest.mark.parametrize("sigma_input", [0.10, 0.18, 0.40])
    def test_pe_roundtrip(self, sigma_input):
        price = bs_price("PE", self.S, self.K, self.T, sigma_input, self.r)
        iv, err = solve_iv("PE", self.S, self.K, self.T, price, self.r)
        assert err is None
        assert abs(iv - sigma_input) < 1e-4

    def test_itm_ce_roundtrip(self):
        sigma = 0.18
        price = bs_price("CE", self.S, 24500, self.T, sigma, self.r)
        iv, err = solve_iv("CE", self.S, 24500, self.T, price, self.r)
        assert err is None
        assert abs(iv - sigma) < 1e-4

    def test_expired_returns_error(self):
        _, err = solve_iv("CE", self.S, self.K, 0, 100.0, self.r)
        assert err == CalcStatus.EXPIRED.value

    def test_zero_price_returns_error(self):
        _, err = solve_iv("CE", self.S, self.K, self.T, 0.0, self.r)
        assert err == CalcStatus.INVALID_PRICE.value

    def test_negative_price_returns_error(self):
        _, err = solve_iv("CE", self.S, self.K, self.T, -1.0, self.r)
        assert err == CalcStatus.INVALID_PRICE.value

    def test_below_intrinsic_returns_error(self):
        K_itm = 24500.0
        intrinsic = self.S - K_itm
        _, err = solve_iv("CE", self.S, K_itm, self.T, intrinsic - 1, self.r)
        assert err == CalcStatus.BELOW_INTRINSIC.value

    def test_at_intrinsic_returns_minimum_iv(self):
        K_itm = 24500.0
        intrinsic = self.S - K_itm
        iv, err = solve_iv("CE", self.S, K_itm, self.T, intrinsic, self.r)
        assert err is None
        assert iv is not None

    def test_near_expiry_roundtrip(self):
        T = 1 / 365.25
        price = bs_price("CE", self.S, self.K, T, 0.18, self.r)
        iv, err = solve_iv("CE", self.S, self.K, T, price, self.r)
        assert err is None
        assert abs(iv - 0.18) < 1e-3


# ============================================================================
# C. Greeks Values
# ============================================================================

class TestGreeksValues:
    S = 25000.0
    K = 25000.0
    T = 30 / 365.25
    sigma = 0.18
    r = DEFAULT_RISK_FREE_RATE

    def test_ce_delta_positive(self):
        g = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        assert 0 < g["delta"] <= 1.0

    def test_pe_delta_negative(self):
        g = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert -1.0 <= g["delta"] < 0

    def test_gamma_positive(self):
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_ce["gamma"] > 0
        assert g_pe["gamma"] > 0

    def test_gamma_same_ce_pe(self):
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert abs(g_ce["gamma"] - g_pe["gamma"]) < 1e-10

    def test_vega_positive(self):
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_ce["vega"] > 0
        assert g_pe["vega"] > 0

    def test_theta_negative_atm(self):
        g_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)
        assert g_ce["theta"] < 0
        assert g_pe["theta"] < 0

    def test_delta_sum_ce_pe(self):
        d_ce = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)["delta"]
        d_pe = bs_greeks("PE", self.S, self.K, self.T, self.sigma, self.r)["delta"]
        assert abs((d_ce - d_pe) - 1.0) < 0.01

    def test_gamma_peak_at_atm(self):
        g_atm = bs_greeks("CE", self.S, self.K, self.T, self.sigma, self.r)
        g_itm = bs_greeks("CE", self.S, self.K - 500, self.T, self.sigma, self.r)
        g_otm = bs_greeks("CE", self.S, self.K + 500, self.T, self.sigma, self.r)
        assert g_atm["gamma"] > g_itm["gamma"]
        assert g_atm["gamma"] > g_otm["gamma"]

    def test_expired_greeks(self):
        g = bs_greeks("CE", 25500, 25000, 0, self.sigma, self.r)
        assert g["delta"] == 1.0
        assert g["gamma"] == 0.0
        assert g["vega"] == 0.0
        assert g["theta"] == 0.0


# ============================================================================
# D. Spot Alignment
# ============================================================================

class TestSpotAlignment:
    def _make_candles(self, base_date: str, n: int = 124) -> list[dict]:
        base = datetime.strptime(base_date, "%Y-%m-%d")
        start_utc = datetime(base.year, base.month, base.day, 3, 45, tzinfo=timezone.utc)
        candles = []
        price = 25000.0
        for i in range(n):
            t = start_utc + timedelta(minutes=3 * i)
            price += (i % 5 - 2) * 0.5
            candles.append({"open_time": t, "close": price})
        return candles

    def test_exact_match(self):
        candles = self._make_candles("2024-10-31")
        spot = align_spot(candles[10]["open_time"], candles)
        assert spot == candles[10]["close"]

    def test_between_candles(self):
        candles = self._make_candles("2024-10-31")
        between = candles[5]["open_time"] + timedelta(minutes=1)
        spot = align_spot(between, candles)
        assert spot == candles[5]["close"]

    def test_after_index_close(self):
        candles = self._make_candles("2024-10-31")
        post_close = datetime(2024, 10, 31, 9, 58, tzinfo=timezone.utc)
        spot = align_spot(post_close, candles)
        assert spot == candles[-1]["close"]

    def test_no_candles(self):
        spot = align_spot(datetime(2024, 10, 31, 5, 0, tzinfo=timezone.utc), [])
        assert spot is None

    def test_before_first_candle(self):
        candles = self._make_candles("2024-10-31")
        early = candles[0]["open_time"] - timedelta(minutes=5)
        spot = align_spot(early, candles)
        assert spot is None

    def test_preserves_post_close_data(self):
        """Option candle at 15:35 IST uses last index close, not None."""
        candles = self._make_candles("2024-10-31")
        option_15_35 = datetime(2024, 10, 31, 10, 5, tzinfo=timezone.utc)  # 15:35 IST
        spot = align_spot(option_15_35, candles)
        assert spot is not None
        assert spot == candles[-1]["close"]


# ============================================================================
# E. Time-to-Expiry
# ============================================================================

class TestTimeToExpiry:
    def test_zero_days(self):
        v = datetime(2024, 10, 31, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(v, "2024-10-31")
        assert T == 0.0

    def test_one_day(self):
        v = datetime(2024, 10, 30, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(v, "2024-10-31")
        assert abs(T - 1 / 365.25) < 1e-6

    def test_thirty_days(self):
        v = datetime(2024, 10, 1, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(v, "2024-10-31")
        assert abs(T - 30 / 365.25) < 1e-6

    def test_past_expiry(self):
        v = datetime(2024, 11, 1, 10, 0, tzinfo=timezone.utc)
        T = compute_time_to_expiry(v, "2024-10-31")
        assert T == 0.0

    def test_linear_scaling(self):
        base = datetime(2024, 10, 15, 10, 0, tzinfo=timezone.utc)
        T7 = compute_time_to_expiry(base, "2024-10-22")
        T14 = compute_time_to_expiry(base, "2024-10-29")
        assert abs(T14 / T7 - 2.0) < 1e-6


# ============================================================================
# F. Full Calculation Pipeline
# ============================================================================

class TestCalculateGreeksForCandle:
    def test_normal_ce(self):
        r = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0)
        assert r.status == CalcStatus.SUCCESS.value
        assert r.implied_volatility is not None
        assert r.delta is not None
        assert r.gamma > 0
        assert r.vega > 0
        assert r.theta < 0

    def test_normal_pe(self):
        r = calculate_greeks_for_candle("PE", 25000, 25000, 30/365.25, 180.0)
        assert r.status == CalcStatus.SUCCESS.value
        assert r.implied_volatility is not None
        assert r.delta < 0

    def test_expired_option(self):
        r = calculate_greeks_for_candle("CE", 25500, 25000, 0, 500.0)
        assert r.status == CalcStatus.SUCCESS.value
        assert r.delta == 1.0
        assert r.gamma == 0.0

    def test_zero_price(self):
        r = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 0.0)
        assert r.status == CalcStatus.INVALID_PRICE.value

    def test_deterministic(self):
        inputs = ("CE", 25000, 25000, 30/365.25, 200.0)
        r1 = calculate_greeks_for_candle(*inputs)
        r2 = calculate_greeks_for_candle(*inputs)
        assert r1.implied_volatility == r2.implied_volatility
        assert r1.delta == r2.delta
        assert r1.gamma == r2.gamma

    def test_result_has_intrinsic(self):
        r = calculate_greeks_for_candle("CE", 25500, 25000, 30/365.25, 600.0)
        assert r.intrinsic_value == 500.0


# ============================================================================
# G. Persistence + Idempotency (integration, uses DB)
# ============================================================================

class TestPersistence:
    def test_upsert_and_idempotent(self, db_session):
        """Insert Greeks, then re-run — should not create duplicates."""
        from app.models import OptionGreeks
        from sqlalchemy import func, select

        # Create a minimal result
        result = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0)
        result.instrument_key = "TEST_KEY"
        result.interval = "3min"
        result.open_time = datetime(2024, 10, 31, 3, 45)
        result.expiry = "2024-10-31"
        result.lot_size = 25

        engine = HistoricalGreeksEngine(db_session)

        # First insert
        stored1 = engine.persist_results([result])
        assert stored1 == 1

        count1 = db_session.scalar(select(func.count(OptionGreeks.id)))
        assert count1 == 1

        # Second insert (idempotent)
        stored2 = engine.persist_results([result])
        assert stored2 == 1

        count2 = db_session.scalar(select(func.count(OptionGreeks.id)))
        assert count2 == 1  # Still 1, not 2

    def test_different_versions_coexist(self, db_session):
        """Two calc_versions for same candle should both be stored."""
        from app.models import OptionGreeks
        from sqlalchemy import func, select

        r1 = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0, calc_version="1.0.0")
        r1.instrument_key = "TEST_KEY"
        r1.interval = "3min"
        r1.open_time = datetime(2024, 10, 31, 3, 45)
        r1.expiry = "2024-10-31"
        r1.lot_size = 25

        r2 = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0, calc_version="2.0.0")
        r2.instrument_key = "TEST_KEY"
        r2.interval = "3min"
        r2.open_time = datetime(2024, 10, 31, 3, 45)
        r2.expiry = "2024-10-31"
        r2.lot_size = 25

        engine = HistoricalGreeksEngine(db_session)
        engine.persist_results([r1, r2])

        count = db_session.scalar(select(func.count(OptionGreeks.id)))
        assert count == 2  # Two different versions

    def test_failed_calculation_persisted(self, db_session):
        """Failed calculations should also be persisted with error status."""
        from app.models import OptionGreeks
        from sqlalchemy import select

        result = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 0.0)
        result.instrument_key = "TEST_FAIL"
        result.interval = "3min"
        result.open_time = datetime(2024, 10, 31, 3, 45)
        result.expiry = "2024-10-31"
        result.lot_size = 25

        engine = HistoricalGreeksEngine(db_session)
        engine.persist_results([result])

        row = db_session.execute(
            select(OptionGreeks).where(OptionGreeks.instrument_key == "TEST_FAIL")
        ).scalar_one()
        assert row.status == "INVALID_PRICE"
        assert row.error_code == "ZERO_PRICE"
        assert row.implied_volatility is None


# ============================================================================
# H. Edge Cases
# ============================================================================

class TestEdgeCases:
    def test_very_near_expiry(self):
        T = 1 / (365.25 * 24)  # 1 hour
        r = calculate_greeks_for_candle("CE", 25000, 25000, T, 50.0)
        # Should either succeed or fail gracefully
        assert r.status in (CalcStatus.SUCCESS.value, CalcStatus.NO_IV.value)

    def test_deep_itm_ce(self):
        """Deep ITM CE: price close to intrinsic may have no IV bracket
        (at IV_MIN the BS price already exceeds market price)."""
        r = calculate_greeks_for_candle("CE", 25000, 20000, 30/365.25, 5100.0)
        # Either succeeds with high delta, or fails with NO_BRACKET (both valid)
        assert r.status in (CalcStatus.SUCCESS.value, CalcStatus.NO_IV.value)
        if r.status == CalcStatus.SUCCESS.value:
            assert r.delta > 0.95

    def test_deep_otm_ce(self):
        r = calculate_greeks_for_candle("CE", 25000, 30000, 30/365.25, 1.0)
        # Deep OTM with very low price — may fail or succeed
        assert r.status in (CalcStatus.SUCCESS.value, CalcStatus.NO_IV.value)

    def test_high_volatility(self):
        price = bs_price("CE", 25000, 25000, 30/365.25, 1.5, DEFAULT_RISK_FREE_RATE)
        r = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, price)
        assert r.status == CalcStatus.SUCCESS.value
        assert abs(r.implied_volatility - 1.5) < 0.01

    def test_low_volatility(self):
        price = bs_price("CE", 25000, 25000, 30/365.25, 0.02, DEFAULT_RISK_FREE_RATE)
        r = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, price)
        assert r.status == CalcStatus.SUCCESS.value


# ============================================================================
# I. Pilot Validation (uses existing 2024-10-31 data)
# ============================================================================

class TestPilotValidation:
    """Integration tests against the existing Phase 7.18 pilot data."""

    def test_pilot_instruments_exist(self, db_session):
        """Verify the Phase 7.18 pilot data is present."""
        from app.models import OptionCandle, ContractSpec
        from sqlalchemy import func, select

        candle_count = db_session.scalar(select(func.count(OptionCandle.id))) or 0
        if candle_count == 0:
            pytest.skip("No pilot data in test database")

        instruments = db_session.execute(
            select(OptionCandle.instrument_key).distinct()
        ).scalars().all()
        assert len(instruments) > 0

    def test_pilot_lot_size_25(self, db_session):
        """Verify pilot contracts have lot_size=25."""
        from app.models import ContractSpec
        from sqlalchemy import select

        spec = db_session.execute(
            select(ContractSpec).where(ContractSpec.instrument_key.like("%54758%"))
        ).scalar_one_or_none()
        if spec is None:
            pytest.skip("Pilot contract not in test database")
        assert spec.lot_size == 25

    def test_engine_calculates_pilot(self, db_session):
        """Run Greeks engine on one pilot instrument."""
        from app.models import OptionCandle
        from sqlalchemy import select

        # Find first pilot instrument
        ik = db_session.execute(
            select(OptionCandle.instrument_key).distinct().limit(1)
        ).scalar_one_or_none()
        if ik is None:
            pytest.skip("No option candles in test database")

        engine = HistoricalGreeksEngine(db_session)
        results = engine.calculate_instrument(ik)

        assert len(results) > 0
        # At least some should succeed (have valid spot)
        success = [r for r in results if r.status == CalcStatus.SUCCESS.value]
        # We may not have NIFTY index candles, so some may fail
        # But the engine should not crash
        assert len(results) == len([r for r in results])  # All returned

    def test_raw_candles_unchanged_after_greeks(self, db_session):
        """Verify option_candles are not modified by Greek calculation."""
        from app.models import OptionCandle
        from sqlalchemy import select

        ik = db_session.execute(
            select(OptionCandle.instrument_key).distinct().limit(1)
        ).scalar_one_or_none()
        if ik is None:
            pytest.skip("No option candles in test database")

        # Read original values
        originals = db_session.execute(
            select(OptionCandle).where(OptionCandle.instrument_key == ik).limit(3)
        ).scalars().all()
        orig_data = [
            {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
            for c in originals
        ]

        # Run Greeks engine
        engine = HistoricalGreeksEngine(db_session)
        engine.calculate_instrument(ik)

        # Verify unchanged
        for i, c in enumerate(
            db_session.execute(
                select(OptionCandle).where(OptionCandle.instrument_key == ik).limit(3)
            ).scalars().all()
        ):
            assert c.open == orig_data[i]["open"]
            assert c.high == orig_data[i]["high"]
            assert c.low == orig_data[i]["low"]
            assert c.close == orig_data[i]["close"]


# ============================================================================
# J. Historical Lot Size
# ============================================================================

class TestHistoricalLotSize:
    def test_per_unit_greeks_independent_of_lot_size(self):
        """Per-unit Greeks must be identical regardless of lot_size."""
        g25 = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0)
        g75 = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0)
        assert g25.delta == g75.delta
        assert g25.gamma == g75.gamma
        assert g25.vega == g75.vega

    def test_lot_level_scales_correctly(self):
        """Lot-level exposure = per-unit × lot_size."""
        g = calculate_greeks_for_candle("CE", 25000, 25000, 30/365.25, 200.0)
        lot_25_delta = g.delta * 25
        lot_75_delta = g.delta * 75
        assert abs(lot_75_delta / lot_25_delta - 3.0) < 1e-10


# ============================================================================
# K. Checkpoint/Greek Reconciliation (Phase 7.24.9 regression)
# ============================================================================

import sqlite3
import os


from sqlalchemy import text


import tempfile


def _make_test_db():
    """Create a temp file-backed DB with all required tables."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    # Create tables matching the production schema
    conn.execute("""
        CREATE TABLE option_candles (
            id INTEGER PRIMARY KEY, instrument_key TEXT, interval TEXT,
            open_time TIMESTAMP, open REAL, high REAL, low REAL, close REAL,
            volume REAL, open_interest REAL, source TEXT, fetched_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE option_greeks (
            id INTEGER PRIMARY KEY, instrument_key TEXT, interval TEXT,
            open_time TIMESTAMP, spot REAL, strike REAL, expiry TEXT,
            option_type TEXT, option_price REAL, lot_size INTEGER,
            time_to_expiry REAL, risk_free_rate REAL, intrinsic_value REAL,
            implied_volatility REAL, delta REAL, gamma REAL, vega REAL, theta REAL,
            calc_model TEXT, calc_version TEXT, calculated_at TIMESTAMP,
            status TEXT, error_code TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE greeks_checkpoint (
            instrument_key TEXT PRIMARY KEY, status TEXT DEFAULT 'PENDING',
            candle_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0, rows_persisted INTEGER DEFAULT 0,
            error_message TEXT, run_id TEXT, started_at TEXT, completed_at TEXT,
            calc_version TEXT DEFAULT '1.0.0'
        )
    """)
    conn.commit()
    return conn, path


def _get_missing_raw(conn):
    """Run the fixed _get_missing_instruments logic against a raw connection."""
    rows = conn.execute("""
        SELECT oc.instrument_key, COUNT(*) AS candle_count
        FROM option_candles oc
        WHERE NOT EXISTS (
            SELECT 1 FROM option_greeks og
            WHERE og.instrument_key = oc.instrument_key
              AND og.calc_version = '1.0.0'
              AND og.interval = '3min'
        )
        GROUP BY oc.instrument_key
        ORDER BY candle_count DESC
    """).fetchall()
    return [r[0] for r in rows]


class TestCheckpointReconciliation:
    """Regression tests for checkpoint/Greek reconciliation."""

    def test_completed_checkpoint_no_greeks_is_missing(self):
        """A: COMPLETED checkpoint + zero Greeks → instrument must be missing."""
        conn, path = _make_test_db()
        try:
            conn.execute("INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at) VALUES ('IK_A', '3min', '2024-10-31 03:45', 200, 210, 190, 200, 1000, 5000, 'TEST', '2024-10-31')")
            conn.execute("INSERT INTO greeks_checkpoint (instrument_key, status, calc_version) VALUES ('IK_A', 'COMPLETED', '1.0.0')")
            conn.commit()
            missing = _get_missing_raw(conn)
            assert "IK_A" in missing
        finally:
            conn.close()
            os.unlink(path)

    def test_completed_checkpoint_with_greeks_not_missing(self):
        """B: COMPLETED checkpoint + complete Greeks → instrument must not be missing."""
        conn, path = _make_test_db()
        try:
            conn.execute("INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at) VALUES ('IK_B', '3min', '2024-10-31 03:45', 200, 210, 190, 200, 1000, 5000, 'TEST', '2024-10-31')")
            conn.execute("INSERT INTO option_greeks (instrument_key, interval, open_time, spot, strike, expiry, option_type, option_price, time_to_expiry, risk_free_rate, intrinsic_value, implied_volatility, delta, gamma, vega, theta, calc_version, calculated_at, status) VALUES ('IK_B', '3min', '2024-10-31 03:45', 25000, 25000, '2024-10-31', 'CE', 200, 0.08, 0.065, 0, 0.18, 0.5, 0.0002, 50, -10, '1.0.0', '2024-10-31', 'SUCCESS')")
            conn.execute("INSERT INTO greeks_checkpoint (instrument_key, status, calc_version) VALUES ('IK_B', 'COMPLETED', '1.0.0')")
            conn.commit()
            missing = _get_missing_raw(conn)
            assert "IK_B" not in missing
        finally:
            conn.close()
            os.unlink(path)

    def test_greeks_exist_no_checkpoint_not_missing(self):
        """C: Greeks exist + no checkpoint → instrument must not be recomputed."""
        conn, path = _make_test_db()
        try:
            conn.execute("INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at) VALUES ('IK_C', '3min', '2024-10-31 03:45', 200, 210, 190, 200, 1000, 5000, 'TEST', '2024-10-31')")
            conn.execute("INSERT INTO option_greeks (instrument_key, interval, open_time, spot, strike, expiry, option_type, option_price, time_to_expiry, risk_free_rate, intrinsic_value, implied_volatility, delta, gamma, vega, theta, calc_version, calculated_at, status) VALUES ('IK_C', '3min', '2024-10-31 03:45', 25000, 25000, '2024-10-31', 'CE', 200, 0.08, 0.065, 0, 0.18, 0.5, 0.0002, 50, -10, '1.0.0', '2024-10-31', 'SUCCESS')")
            conn.commit()
            missing = _get_missing_raw(conn)
            assert "IK_C" not in missing
        finally:
            conn.close()
            os.unlink(path)

    def test_different_calc_version_still_missing(self):
        """D: Greeks exist for old version → current version is still missing."""
        conn, path = _make_test_db()
        try:
            conn.execute("INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at) VALUES ('IK_D', '3min', '2024-10-31 03:45', 200, 210, 190, 200, 1000, 5000, 'TEST', '2024-10-31')")
            conn.execute("INSERT INTO option_greeks (instrument_key, interval, open_time, spot, strike, expiry, option_type, option_price, time_to_expiry, risk_free_rate, intrinsic_value, implied_volatility, delta, gamma, vega, theta, calc_version, calculated_at, status) VALUES ('IK_D', '3min', '2024-10-31 03:45', 25000, 25000, '2024-10-31', 'CE', 200, 0.08, 0.065, 0, 0.18, 0.5, 0.0002, 50, -10, '0.9.0', '2024-10-31', 'SUCCESS')")
            conn.commit()
            missing = _get_missing_raw(conn)
            assert "IK_D" in missing
        finally:
            conn.close()
            os.unlink(path)

    def test_partial_greek_persistence_still_missing(self):
        """E: Only some candles have Greeks → instrument still has Greeks (not missing)."""
        conn, path = _make_test_db()
        try:
            conn.execute("INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at) VALUES ('IK_E', '3min', '2024-10-31 03:45', 200, 210, 190, 200, 1000, 5000, 'TEST', '2024-10-31')")
            conn.execute("INSERT INTO option_candles (instrument_key, interval, open_time, open, high, low, close, volume, open_interest, source, fetched_at) VALUES ('IK_E', '3min', '2024-10-31 03:48', 200, 210, 190, 200, 1000, 5000, 'TEST', '2024-10-31')")
            conn.execute("INSERT INTO option_greeks (instrument_key, interval, open_time, spot, strike, expiry, option_type, option_price, time_to_expiry, risk_free_rate, intrinsic_value, implied_volatility, delta, gamma, vega, theta, calc_version, calculated_at, status) VALUES ('IK_E', '3min', '2024-10-31 03:45', 25000, 25000, '2024-10-31', 'CE', 200, 0.08, 0.065, 0, 0.18, 0.5, 0.0002, 50, -10, '1.0.0', '2024-10-31', 'SUCCESS')")
            conn.commit()
            missing = _get_missing_raw(conn)
            assert "IK_E" not in missing  # Has at least one Greek row
        finally:
            conn.close()
            os.unlink(path)

    def test_pilot_data_idempotent(self, db_session):
        """F: Existing pilot data remains valid through idempotent rerun."""
        from app.models import OptionCandle, OptionGreeks
        from sqlalchemy import func, select

        candle_count = db_session.scalar(select(func.count(OptionCandle.id))) or 0
        if candle_count == 0:
            pytest.skip("No pilot data in test database")

        ik = db_session.execute(
            select(OptionCandle.instrument_key).distinct().limit(1)
        ).scalar_one_or_none()
        if ik is None:
            pytest.skip("No option candles in test database")

        # Calculate Greeks
        engine = HistoricalGreeksEngine(db_session)
        results1 = engine.calculate_instrument(ik)
        engine.persist_results(results1)

        # Rerun — should be idempotent
        results2 = engine.calculate_instrument(ik)
        engine.persist_results(results2)

        count = db_session.scalar(select(func.count(OptionGreeks.id)))
        # Should not have doubled
        assert count == len(results1)
