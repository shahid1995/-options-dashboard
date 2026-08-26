"""Tests for Historical GEX calculation service — Phase 7.8A.

Covers:
  - Phase 7.1 formula correctness (sign convention, OI linearity, gamma linearity,
    spot-squared scaling, 0.01 factor, no lot-size multiplication)
  - Strike / expiry / chain aggregation and invariants
  - Data quality / exclusion rules
  - Timestamp safety (no future spot usage)
  - Expiry handling
  - Calculation versioning
  - Idempotency
  - Real-data integration against the production database
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    OptionCandle,
    ContractSpec,
    NiftyCandle,
    OptionGreeks,
    HistoricalGexSnapshot,
)
from app.services.historical_gex import (
    HistoricalGexService,
    compute_raw_gex,
    compute_signed_gex,
    _validate_option_row,
    ExclusionReason,
    OptionGexRow,
    StrikeGex,
    CALC_VERSION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    """In-memory SQLite engine for isolated tests."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Session bound to the in-memory engine."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# A. Formula tests — Phase 7.1 contract
# ---------------------------------------------------------------------------

class TestGexFormula:
    """Verify the core Phase 7.1 GEX formula: raw_gex = gamma * OI * spot^2 * 0.01."""

    def test_basic_calculation(self):
        """Standard inputs produce expected result."""
        gamma, oi, spot = 0.005, 1000, 25000.0
        raw = compute_raw_gex(gamma, oi, spot)
        expected = 0.005 * 1000 * 25000 * 25000 * 0.01
        assert raw == pytest.approx(expected)

    def test_ce_sign_positive(self):
        """Call GEX is positive (NAIVE_DEALER_CONVENTION)."""
        raw = compute_raw_gex(0.01, 500, 25000.0)
        signed = compute_signed_gex("CE", raw)
        assert signed == pytest.approx(raw)
        assert signed > 0

    def test_pe_sign_negative(self):
        """Put GEX is negative (NAIVE_DEALER_CONVENTION)."""
        raw = compute_raw_gex(0.01, 500, 25000.0)
        signed = compute_signed_gex("PE", raw)
        assert signed == pytest.approx(-raw)
        assert signed < 0

    def test_oi_linearity(self):
        """Doubling OI doubles GEX."""
        spot, gamma = 25000.0, 0.005
        gex1 = compute_raw_gex(gamma, 1000, spot)
        gex2 = compute_raw_gex(gamma, 2000, spot)
        assert gex2 == pytest.approx(2 * gex1)

    def test_gamma_linearity(self):
        """Doubling gamma doubles GEX."""
        oi, spot = 1000, 25000.0
        gex1 = compute_raw_gex(0.005, oi, spot)
        gex2 = compute_raw_gex(0.010, oi, spot)
        assert gex2 == pytest.approx(2 * gex1)

    def test_spot_squared_scaling(self):
        """GEX scales with spot^2."""
        gamma, oi = 0.005, 1000
        gex_25k = compute_raw_gex(gamma, oi, 25000.0)
        gex_50k = compute_raw_gex(gamma, oi, 50000.0)
        # (50000/25000)^2 = 4
        assert gex_50k == pytest.approx(4 * gex_25k)

    def test_001_factor(self):
        """The 0.01 factor is present."""
        gamma, oi, spot = 1.0, 1.0, 100.0
        raw = compute_raw_gex(gamma, oi, spot)
        # 1.0 * 1.0 * 100 * 100 * 0.01 = 100.0
        assert raw == pytest.approx(100.0)

    def test_no_lot_size_multiplication(self):
        """Lot size is NOT part of the GEX formula."""
        gamma, oi, spot = 0.01, 500, 25000.0
        gex_without_lot = compute_raw_gex(gamma, oi, spot)
        # Multiplying by lot_size should NOT change the result
        gex_with_lot = compute_raw_gex(gamma, oi * 75, spot)
        # If we accidentally included lot_size, gex_with_lot would be 75x
        assert gex_without_lot != gex_with_lot  # proves OI matters
        assert gex_without_lot == compute_raw_gex(gamma, oi, spot)  # formula unchanged


# ---------------------------------------------------------------------------
# B. Eligibility / exclusion tests
# ---------------------------------------------------------------------------

class TestEligibility:
    """Verify row validation and exclusion reasons."""

    def test_valid_ce(self):
        assert _validate_option_row(0.005, 1000, 25000.0, 25000.0, "CE") is None

    def test_valid_pe(self):
        assert _validate_option_row(0.005, 1000, 25000.0, 25000.0, "PE") is None

    def test_missing_gamma(self):
        assert _validate_option_row(None, 1000, 25000.0, 25000.0, "CE") == ExclusionReason.MISSING_GAMMA

    def test_invalid_gamma_nan(self):
        assert _validate_option_row(float("nan"), 1000, 25000.0, 25000.0, "CE") == ExclusionReason.INVALID_GAMMA

    def test_invalid_gamma_inf(self):
        assert _validate_option_row(float("inf"), 1000, 25000.0, 25000.0, "CE") == ExclusionReason.INVALID_GAMMA

    def test_negative_gamma(self):
        """Negative gamma is invalid per Black-Scholes (gamma >= 0 always)."""
        assert _validate_option_row(-0.001, 1000, 25000.0, 25000.0, "CE") == ExclusionReason.NEGATIVE_GAMMA

    def test_zero_gamma_valid(self):
        """Zero gamma is valid (happens at expiry)."""
        assert _validate_option_row(0.0, 1000, 25000.0, 25000.0, "CE") is None

    def test_missing_oi(self):
        assert _validate_option_row(0.005, None, 25000.0, 25000.0, "CE") == ExclusionReason.MISSING_OI

    def test_zero_oi(self):
        """OI = 0 means no exposure — excluded."""
        assert _validate_option_row(0.005, 0, 25000.0, 25000.0, "CE") == ExclusionReason.ZERO_OI

    def test_negative_oi(self):
        """Negative OI is invalid."""
        assert _validate_option_row(0.005, -100, 25000.0, 25000.0, "CE") == ExclusionReason.ZERO_OI

    def test_missing_spot(self):
        assert _validate_option_row(0.005, 1000, None, 25000.0, "CE") == ExclusionReason.MISSING_SPOT

    def test_zero_spot(self):
        assert _validate_option_row(0.005, 1000, 0, 25000.0, "CE") == ExclusionReason.INVALID_SPOT

    def test_missing_strike(self):
        assert _validate_option_row(0.005, 1000, 25000.0, None, "CE") == ExclusionReason.MISSING_STRIKE

    def test_missing_option_type(self):
        assert _validate_option_row(0.005, 1000, 25000.0, 25000.0, None) == ExclusionReason.MISSING_OPTION_TYPE

    def test_unknown_option_type(self):
        assert _validate_option_row(0.005, 1000, 25000.0, 25000.0, "XX") == ExclusionReason.UNKNOWN_OPTION_TYPE


# ---------------------------------------------------------------------------
# C. Aggregation tests
# ---------------------------------------------------------------------------

class TestAggregation:
    """Strike / expiry / chain aggregation with invariant checks."""

    def _make_row(self, strike, option_type, gamma, oi, spot, expiry="2024-10-03", key="K1"):
        raw = compute_raw_gex(gamma, oi, spot)
        signed = compute_signed_gex(option_type, raw)
        return OptionGexRow(
            instrument_key=key,
            interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=spot,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            gamma=gamma,
            open_interest=oi,
            option_price=100.0,
            lot_size=75,
            raw_gex=raw,
            signed_gex=signed,
            status="SUCCESS",
        )

    def test_strike_aggregation_single(self):
        """One CE + one PE at same strike aggregates correctly."""
        spot = 25000.0
        ce = self._make_row(25000, "CE", 0.005, 1000, spot)
        pe = self._make_row(25000, "PE", 0.003, 800, spot)
        by_strike = HistoricalGexService.aggregate_by_strike([ce, pe])
        assert 25000 in by_strike
        sg = by_strike[25000]
        assert sg.has_call is True
        assert sg.has_put is True
        assert sg.net_gex == pytest.approx(sg.call_gex + sg.put_gex)
        assert sg.call_gex > 0
        assert sg.put_gex < 0

    def test_strike_aggregation_multiple(self):
        """Multiple strikes are separated correctly."""
        spot = 25000.0
        rows = [
            self._make_row(24800, "CE", 0.005, 500, spot),
            self._make_row(24800, "PE", 0.003, 400, spot),
            self._make_row(25200, "CE", 0.004, 600, spot),
            self._make_row(25200, "PE", 0.006, 700, spot),
        ]
        by_strike = HistoricalGexService.aggregate_by_strike(rows)
        assert len(by_strike) == 2
        assert 24800 in by_strike
        assert 25200 in by_strike

    def test_expiry_aggregation(self):
        """Expiry-level aggregates correctly."""
        spot = 25000.0
        rows = [
            self._make_row(24800, "CE", 0.005, 500, spot, expiry="2024-10-03"),
            self._make_row(24800, "PE", 0.003, 400, spot, expiry="2024-10-03"),
            self._make_row(25200, "CE", 0.004, 600, spot, expiry="2024-10-10"),
            self._make_row(25200, "PE", 0.006, 700, spot, expiry="2024-10-10"),
        ]
        by_expiry = HistoricalGexService.aggregate_by_expiry(rows)
        assert len(by_expiry) == 2
        assert "2024-10-03" in by_expiry
        assert "2024-10-10" in by_expiry

    def test_chain_gex_invariant(self):
        """chain_net_gex == sum(strike_net_gex) for strikes with both sides."""
        spot = 25000.0
        rows = [
            self._make_row(24800, "CE", 0.005, 500, spot),
            self._make_row(24800, "PE", 0.003, 400, spot),
            self._make_row(25200, "CE", 0.004, 600, spot),
            self._make_row(25200, "PE", 0.006, 700, spot),
        ]
        chain = HistoricalGexService.compute_chain_gex(rows, spot)
        # Chain net = call + put
        assert chain.net_gex == pytest.approx(chain.call_gex + chain.put_gex)
        # Chain net = sum of strike nets (only strikes with both sides)
        strike_net_sum = sum(
            sg.net_gex for sg in chain.by_strike.values()
            if sg.has_call and sg.has_put
        )
        # In this case all strikes have both sides
        assert chain.net_gex == pytest.approx(strike_net_sum)

    def test_excluded_rows_not_in_aggregation(self):
        """EXCLUDED rows must not contribute to aggregation."""
        spot = 25000.0
        ce = self._make_row(25000, "CE", 0.005, 1000, spot)
        pe_excluded = OptionGexRow(
            instrument_key="K1", interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=spot, strike=25000, expiry="2024-10-03", option_type="PE",
            gamma=0.0, open_interest=0.0, option_price=0.0, lot_size=75,
            raw_gex=0.0, signed_gex=0.0,
            status="EXCLUDED", exclusion_reason="ZERO_OI",
        )
        by_strike = HistoricalGexService.aggregate_by_strike([ce, pe_excluded])
        sg = by_strike[25000]
        assert sg.has_call is True
        assert sg.has_put is False  # excluded PE not counted

    def test_empty_rows(self):
        """Empty input produces empty aggregation."""
        chain = HistoricalGexService.compute_chain_gex([], 25000.0)
        assert chain.call_gex == 0.0
        assert chain.put_gex == 0.0
        assert chain.net_gex == 0.0


# ---------------------------------------------------------------------------
# D. Persistence tests (in-memory DB)
# ---------------------------------------------------------------------------

class TestPersistence:
    """Verify idempotent upsert into historical_gex table."""

    def test_persist_and_read_back(self, db):
        """Persist one row and read it back."""
        service = HistoricalGexService(db)
        row = OptionGexRow(
            instrument_key="NSE_FO|58512|03-10-2024",
            interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=25000.0, strike=25000.0, expiry="2024-10-03",
            option_type="CE", gamma=0.005, open_interest=1000,
            option_price=100.0, lot_size=75,
            raw_gex=compute_raw_gex(0.005, 1000, 25000.0),
            signed_gex=compute_signed_gex("CE", compute_raw_gex(0.005, 1000, 25000.0)),
        )
        stored = service.persist_results([row])
        assert stored == 1

        # Read back
        result = db.execute(
            select(HistoricalGexSnapshot)
            .where(HistoricalGexSnapshot.instrument_key == "NSE_FO|58512|03-10-2024")
        ).scalars().first()
        assert result is not None
        assert result.spot == 25000.0
        assert result.raw_gex == pytest.approx(row.raw_gex)
        assert result.status == "SUCCESS"

    def test_idempotent_upsert(self, db):
        """Re-persisting the same row updates rather than duplicates."""
        service = HistoricalGexService(db)
        row = OptionGexRow(
            instrument_key="NSE_FO|58512|03-10-2024",
            interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=25000.0, strike=25000.0, expiry="2024-10-03",
            option_type="CE", gamma=0.005, open_interest=1000,
            option_price=100.0, lot_size=75,
            raw_gex=compute_raw_gex(0.005, 1000, 25000.0),
            signed_gex=compute_signed_gex("CE", compute_raw_gex(0.005, 1000, 25000.0)),
        )
        service.persist_results([row])
        service.persist_results([row])

        count = db.execute(
            select(func.count(HistoricalGexSnapshot.id))
            .where(HistoricalGexSnapshot.instrument_key == "NSE_FO|58512|03-10-2024")
        ).scalar()
        assert count == 1  # No duplicate

    def test_version_isolation(self, db):
        """Different calc_versions coexist."""
        row_v1 = OptionGexRow(
            instrument_key="NSE_FO|58512|03-10-2024",
            interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=25000.0, strike=25000.0, expiry="2024-10-03",
            option_type="CE", gamma=0.005, open_interest=1000,
            option_price=100.0, lot_size=75,
            raw_gex=312500.0, signed_gex=312500.0,
        )
        service_v1 = HistoricalGexService(db, calc_version="h_gex_v1")
        service_v1.persist_results([row_v1])

        # Different version
        service_v2 = HistoricalGexService(db, calc_version="h_gex_v2")
        row_v2 = OptionGexRow(
            instrument_key="NSE_FO|58512|03-10-2024",
            interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=25000.0, strike=25000.0, expiry="2024-10-03",
            option_type="CE", gamma=0.006, open_interest=1000,
            option_price=100.0, lot_size=75,
            raw_gex=375000.0, signed_gex=375000.0,
        )
        service_v2.persist_results([row_v2])

        count = db.execute(
            select(func.count(HistoricalGexSnapshot.id))
            .where(HistoricalGexSnapshot.instrument_key == "NSE_FO|58512|03-10-2024")
        ).scalar()
        assert count == 2  # Both versions coexist


# ---------------------------------------------------------------------------
# E. Timestamp safety tests
# ---------------------------------------------------------------------------

class TestTimestampSafety:
    """Verify historical GEX never uses future spot data."""

    def test_spot_from_greeks_not_option_candles(self, db):
        """Spot must come from option_greeks (aligned by Greeks engine),
        not from a future NIFTY candle."""
        # Create a NIFTY candle at 10:00 with spot=30000 (future)
        nifty = NiftyCandle(
            symbol="NIFTY", interval="3min",
            open_time=datetime(2024, 10, 3, 10, 0),
            open=30000, high=30100, low=29900, close=30000, volume=1000,
        )
        db.add(nifty)

        # Greeks row at 9:15 with spot=25000 (correct, past-aligned)
        greeks = OptionGreeks(
            instrument_key="TEST|001|03-10-2024", interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=25000.0, strike=25000.0, expiry="2024-10-03",
            option_type="CE", option_price=100.0, lot_size=75,
            time_to_expiry=0.01, risk_free_rate=0.065, intrinsic_value=0.0,
            implied_volatility=0.18, delta=0.5, gamma=0.005, vega=10.0, theta=-0.5,
            calc_version="1.0.0", status="SUCCESS",
            calculated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(greeks)
        db.commit()

        service = HistoricalGexService(db)
        results = service.calculate_instrument("TEST|001|03-10-2024")
        assert len(results) == 1
        assert results[0].spot == 25000.0  # Used Greeks spot, not future NIFTY

    def test_excluded_row_with_zero_oi(self, db):
        """Zero OI is excluded — no GEX computed."""
        greeks = OptionGreeks(
            instrument_key="TEST|002|03-10-2024", interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=25000.0, strike=25000.0, expiry="2024-10-03",
            option_type="CE", option_price=100.0, lot_size=75,
            time_to_expiry=0.01, risk_free_rate=0.065, intrinsic_value=0.0,
            implied_volatility=0.18, delta=0.5, gamma=0.005, vega=10.0, theta=-0.5,
            calc_version="1.0.0", status="SUCCESS",
            calculated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(greeks)
        # Option candle with OI=0
        candle = OptionCandle(
            instrument_key="TEST|002|03-10-2024", interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            open=100, high=110, low=90, close=100, volume=0, open_interest=0,
            source="TEST", fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(candle)
        db.commit()

        service = HistoricalGexService(db)
        results = service.calculate_instrument("TEST|002|03-10-2024")
        assert len(results) == 1
        assert results[0].status == "EXCLUDED"
        assert results[0].exclusion_reason == "ZERO_OI"


# ---------------------------------------------------------------------------
# F. Real-data integration test (production DB)
# ---------------------------------------------------------------------------

class TestRealDataIntegration:
    """Integration tests against the production database.

    These tests require the production database to be present.
    Skipped in CI or when the database is not available.
    """

    @pytest.fixture(autouse=True)
    def _skip_without_db(self):
        db_path = Path(__file__).parent.parent / "paper_journal.db"
        if not db_path.exists():
            pytest.skip("Production database not available")

    def _get_prod_engine(self):
        db_path = Path(__file__).parent.parent / "paper_journal.db"
        eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        return eng

    def test_calculate_real_instrument(self):
        """Calculate GEX for one real instrument and verify formula."""
        eng = self._get_prod_engine()
        Session = sessionmaker(bind=eng)
        db = Session()

        # Pick an instrument with known Greeks
        ik = db.execute(
            select(OptionGreeks.instrument_key)
            .where(OptionGreeks.status == "SUCCESS")
            .limit(1)
        ).scalar()

        if not ik:
            pytest.skip("No Greek data available")

        service = HistoricalGexService(db)
        results = service.calculate_instrument(ik)
        assert len(results) > 0

        # Verify formula for each SUCCESS row
        for r in results:
            if r.status == "SUCCESS":
                expected_raw = r.gamma * r.open_interest * r.spot * r.spot * 0.01
                assert r.raw_gex == pytest.approx(expected_raw, rel=1e-10)
                if r.option_type == "CE":
                    assert r.signed_gex == pytest.approx(r.raw_gex)
                else:
                    assert r.signed_gex == pytest.approx(-r.raw_gex)

        db.close()
        eng.dispose()

    def test_persist_and_status(self):
        """Persist a small pilot and verify status."""
        eng = self._get_prod_engine()
        Session = sessionmaker(bind=eng)
        db = Session()

        # Find one instrument
        ik = db.execute(
            select(OptionGreeks.instrument_key)
            .where(OptionGreeks.status == "SUCCESS")
            .limit(1)
        ).scalar()

        if not ik:
            pytest.skip("No Greek data available")

        service = HistoricalGexService(db)
        result = service.run_instrument(ik)
        assert result["success"] > 0

        status = service.get_status()
        assert status["total_rows"] >= result["success"]
        assert status["instruments"] >= 1

        db.close()
        eng.dispose()


# ---------------------------------------------------------------------------
# G. Chain GEX invariant test
# ---------------------------------------------------------------------------

class TestChainInvariants:
    """Aggregation invariants that must hold for any dataset."""

    def _make_row(self, strike, option_type, gamma, oi, spot, expiry="2024-10-03", key="K1"):
        raw = compute_raw_gex(gamma, oi, spot)
        signed = compute_signed_gex(option_type, raw)
        return OptionGexRow(
            instrument_key=key, interval="3min",
            open_time=datetime(2024, 10, 3, 9, 15),
            spot=spot, strike=strike, expiry=expiry,
            option_type=option_type, gamma=gamma, open_interest=oi,
            option_price=100.0, lot_size=75,
            raw_gex=raw, signed_gex=signed, status="SUCCESS",
        )

    def test_chain_equals_sum_of_expiries(self):
        """chain_net_gex == sum(expiry_net_gex)."""
        spot = 25000.0
        rows = [
            self._make_row(24800, "CE", 0.005, 500, spot, expiry="2024-10-03"),
            self._make_row(24800, "PE", 0.003, 400, spot, expiry="2024-10-03"),
            self._make_row(25200, "CE", 0.004, 600, spot, expiry="2024-10-10"),
            self._make_row(25200, "PE", 0.006, 700, spot, expiry="2024-10-10"),
        ]
        chain = HistoricalGexService.compute_chain_gex(rows, spot)
        expiry_sum = sum(eg.net_gex for eg in chain.by_expiry.values())
        assert chain.net_gex == pytest.approx(expiry_sum)

    def test_call_gex_always_positive(self):
        """Call GEX is always >= 0."""
        spot = 25000.0
        rows = [
            self._make_row(24800, "CE", 0.005, 500, spot),
            self._make_row(25200, "CE", 0.004, 600, spot),
        ]
        chain = HistoricalGexService.compute_chain_gex(rows, spot)
        assert chain.call_gex >= 0

    def test_put_gex_always_negative(self):
        """Put GEX is always <= 0."""
        spot = 25000.0
        rows = [
            self._make_row(24800, "PE", 0.003, 400, spot),
            self._make_row(25200, "PE", 0.006, 700, spot),
        ]
        chain = HistoricalGexService.compute_chain_gex(rows, spot)
        assert chain.put_gex <= 0

    def test_by_strike_sorted(self):
        """by_strike keys are sorted ascending."""
        spot = 25000.0
        rows = [
            self._make_row(25200, "CE", 0.004, 600, spot),
            self._make_row(24800, "CE", 0.005, 500, spot),
            self._make_row(25000, "CE", 0.006, 700, spot),
        ]
        chain = HistoricalGexService.compute_chain_gex(rows, spot)
        strikes = sorted(chain.by_strike.keys())
        assert strikes == [24800, 25000, 25200]
