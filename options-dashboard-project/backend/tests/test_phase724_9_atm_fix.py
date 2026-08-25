"""Phase 7.24.9 — ATM Calculation Fix & NIFTY Backfill Coverage Tests.

Tests for the two P0 fixes:
  1. _calculate_historical_atm() now uses the expiry-day opening candle
     (09:15) instead of the previous trading day's close.
  2. run_nifty() defaults to covering the full contract-registry range
     instead of only the last 180 days.

All tests use in-memory SQLite.  No real Upstox API calls are made.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ContractSpec,
    NiftyCandle,
)
from app.services.backfill_orchestrator import (
    BackfillOrchestrator,
    NIFTY_INDEX_KEY,
    NIFTY_SYMBOL,
    DEFAULT_INTERVAL_STR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class _MockTokenProvider:
    def __init__(self, token="test-token"):
        self._token = token

    def get_token(self):
        return self._token


def _mock_client():
    client = AsyncMock()
    client._token_provider = _MockTokenProvider()
    client.get_expiries = AsyncMock(return_value=[])
    client.get_contracts = AsyncMock(return_value=[])
    client.get_historical_candles = AsyncMock(return_value=[])
    client.get_expired_historical_candles = AsyncMock(return_value=[])
    client.metrics = MagicMock()
    client.metrics.snapshot.return_value = {"total_requests": 0}
    return client


def _add_spec(db, ik, expiry, strike, opt_type="CE", lot=75):
    spec = ContractSpec(
        instrument_key=ik,
        underlying="NIFTY",
        underlying_key=NIFTY_INDEX_KEY,
        expiry=expiry,
        strike_price=strike,
        instrument_type=opt_type,
        lot_size=lot,
        minimum_lot=lot,
        trading_symbol=f"NIFTY{expiry.replace('-', '')}{int(strike)}{opt_type}",
        segment="NSE_FO",
        exchange="NSE",
        source="TEST",
        source_reference="test",
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(spec)
    db.commit()
    return spec


def _add_nifty_candle(db, d, open_price, interval="3min", hour=9, minute=15):
    """Add a single NIFTY candle on date *d* at the given time."""
    dt = datetime(d.year, d.month, d.day, hour, minute)
    db.add(
        NiftyCandle(
            symbol="NIFTY",
            interval=interval,
            open_time=dt,
            open=open_price,
            high=open_price + 20,
            low=open_price - 20,
            close=open_price + 10,
            volume=15000,
        )
    )
    db.commit()


def _add_nifty_candles_full_day(db, d, open_price, interval="3min"):
    """Add a full trading day of NIFTY candles (09:15 – 15:27, 3-min)."""
    from datetime import timedelta as td

    current = datetime(d.year, d.month, d.day, 9, 15)
    end = datetime(d.year, d.month, d.day, 15, 27)
    candle_open = open_price
    while current <= end:
        db.add(
            NiftyCandle(
                symbol="NIFTY",
                interval=interval,
                open_time=current,
                open=candle_open,
                high=candle_open + 20,
                low=candle_open - 20,
                close=candle_open + 10,
                volume=15000,
            )
        )
        current += td(minutes=3)
    db.commit()


def _add_nifty_candles_multi_day(db, date_prices, interval="3min"):
    """Add candles for multiple days. *date_prices* = [(date, open_price), ...]"""
    for d, price in date_prices:
        _add_nifty_candle(db, d, price, interval)


# ===========================================================================
# 1. EXPIRY-DAY OPENING CANDLE SELECTION
# ===========================================================================


class TestExpiryDayOpeningCandle:
    """Verify that _calculate_historical_atm() uses the first candle on the
    expiry date (09:15 opening candle), not the previous day's close."""

    def test_uses_opening_candle_on_expiry_date(self, db):
        """ATM ref price should be the 09:15 open on the expiry date."""
        # Previous day: 2026-03-02 — open at 25169.80
        # Expiry day: 2026-03-03 — open at 24659.25
        _add_nifty_candle(db, date(2026, 3, 2), 25169.80)
        _add_nifty_candle(db, date(2026, 3, 3), 24659.25)

        strikes = [24650, 24700, 25150, 25200]
        for s in strikes:
            _add_spec(db, f"IK_{s}_CE", "2026-03-03", s, "CE")
            _add_spec(db, f"IK_{s}_PE", "2026-03-03", s, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-03-03")

        # Should use 24659.25 → nearest strike 24650
        assert atm == 24650, (
            f"Expected ATM 24650 (from expiry open 24659.25), got {atm}"
        )

    def test_previous_day_close_not_used(self, db):
        """If the previous day's close differs significantly from the
        expiry-day open, the ATM must reflect the expiry-day open."""
        # Previous day close: NIFTY opened at 26000 on Feb 27
        _add_nifty_candle(db, date(2026, 2, 27), 26000.0)
        # Expiry day open: 24659.25 on Mar 2
        _add_nifty_candle(db, date(2026, 3, 2), 24659.25)

        strikes = [24650, 24700, 26000, 26050]
        for s in strikes:
            _add_spec(db, f"IK_{s}_CE", "2026-03-02", s, "CE")
            _add_spec(db, f"IK_{s}_PE", "2026-03-02", s, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-03-02")

        # Must be 24650 (from expiry open), NOT 26000 (from prev close)
        assert atm == 24650, (
            f"ATM should use expiry open (24650), not prev close (26000). Got {atm}"
        )

    def test_uses_first_candle_not_last(self, db):
        """When multiple candles exist on the expiry date, use the earliest."""
        _add_nifty_candle(db, date(2026, 5, 12), 23722.60, hour=9, minute=15)
        _add_nifty_candle(db, date(2026, 5, 12), 23812.60, hour=9, minute=18)
        _add_nifty_candle(db, date(2026, 5, 12), 23850.00, hour=15, minute=27)

        strikes = [23700, 23800, 23850]
        for s in strikes:
            _add_spec(db, f"IK_{s}_CE", "2026-05-12", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-05-12")

        # 09:15 open = 23722.60 → nearest strike = 23700
        assert atm == 23700, (
            f"Should use first candle (23722.60→23700), got {atm}"
        )

    def test_only_previous_day_candles_returns_none(self, db):
        """If no candles exist on the expiry date itself, return None."""
        _add_nifty_candle(db, date(2026, 4, 30), 25000.0)
        # No candle on 2026-05-01

        _add_spec(db, "IK_25000", "2026-05-01", 25000, "CE")
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-05-01")

        assert atm is None, (
            "Should return None when no candles exist on the expiry date"
        )


# ===========================================================================
# 2. PREVIOUS-DAY CLOSE MUST NOT BE SELECTED
# ===========================================================================


class TestPreviousDayCloseRejection:
    """Ensure the old buggy behavior (using previous day's close) is gone."""

    def test_gap_down_day_uses_day_open(self, db):
        """On a gap-down day, the previous close must not be the ref price."""
        _add_nifty_candle(db, date(2026, 4, 10), 24500.0)  # prev day
        _add_nifty_candle(db, date(2026, 4, 13), 23589.60)  # gap down

        strikes = [23600, 23650, 24500, 24550]
        for s in strikes:
            _add_spec(db, f"IK_{s}_CE", "2026-04-13", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-04-13")

        assert atm == 23600, (
            f"Expected ATM 23600 from gap-down open (23589.60), got {atm}"
        )

    def test_gap_up_day_uses_day_open(self, db):
        """On a gap-up day, the previous close must not be the ref price."""
        _add_nifty_candle(db, date(2026, 3, 2), 24000.0)  # prev day
        _add_nifty_candle(db, date(2026, 3, 3), 25169.80)  # gap up

        strikes = [25150, 25200, 24000, 24050]
        for s in strikes:
            _add_spec(db, f"IK_{s}_PE", "2026-03-03", s, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-03-03")

        assert atm == 25150, (
            f"Expected ATM 25150 from gap-up open (25169.80), got {atm}"
        )


# ===========================================================================
# 3. ATM CALCULATION AROUND STRIKE BOUNDARIES
# ===========================================================================


class TestStrikeBoundaryATM:
    """Test ATM correctness near strike spacing boundaries."""

    def test_price_exactly_on_strike(self, db):
        """When opening price is exactly on a strike, that strike is ATM."""
        _add_nifty_candle(db, date(2026, 6, 1), 24000.0)

        strikes = [23950, 24000, 24050]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-06-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-06-01")
        assert atm == 24000

    def test_price_between_strikes_closer_to_lower(self, db):
        """Price 24020 → closer to 24000 than 24050 (NIFTY 50-pt spacing)."""
        _add_nifty_candle(db, date(2026, 6, 1), 24020.0)

        strikes = [23950, 24000, 24050, 24100]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-06-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-06-01")
        assert atm == 24000

    def test_price_between_strikes_closer_to_upper(self, db):
        """Price 24030 → closer to 24050 than 24000."""
        _add_nifty_candle(db, date(2026, 6, 1), 24030.0)

        strikes = [23950, 24000, 24050, 24100]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-06-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-06-01")
        assert atm == 24050

    def test_price_exactly_midpoint_rounds_to_nearest(self, db):
        """Price exactly between two strikes picks the first one found
        (min by abs diff — both equal, min returns the smaller strike)."""
        _add_nifty_candle(db, date(2026, 6, 1), 24025.0)

        strikes = [24000, 24050]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-06-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-06-01")
        # Both are equidistant; min() returns 24000 (first in sorted order)
        assert atm == 24000

    def test_very_high_price_near_top_strike(self, db):
        """Price near the highest available strike is rounded correctly."""
        _add_nifty_candle(db, date(2026, 7, 1), 25480.0)

        strikes = [25400, 25450, 25500]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-07-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-07-01")
        assert atm == 25500

    def test_very_low_price_near_bottom_strike(self, db):
        """Price near the lowest available strike is rounded correctly."""
        _add_nifty_candle(db, date(2026, 7, 1), 22020.0)

        strikes = [22000, 22050, 22100]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-07-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-07-01")
        assert atm == 22000

    def test_nifty_50_point_spacing_atm(self, db):
        """Typical NIFTY 50-point spacing: 24343.85 → 24350 (nearest)."""
        _add_nifty_candle(db, date(2026, 8, 11), 24575.10)

        strikes = [24500, 24550, 24600, 24650, 24700]
        for s in strikes:
            _add_spec(db, f"IK_{s}", "2026-08-11", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        atm = orch._calculate_historical_atm("2026-08-11")
        # 24575.10 → nearest to 24600 (diff=24.9) vs 24550 (diff=25.1)
        assert atm == 24600


# ===========================================================================
# 4. EXPIRIES WITH MISSING NIFTY DATA
# ===========================================================================


class TestMissingNiftyData:
    """When NIFTY candles are missing for an expiry, ATM returns None."""

    def test_no_nifty_candles_at_all(self, db):
        """Empty database → ATM is None."""
        _add_spec(db, "IK_25000", "2026-01-05", 25000, "CE")
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        assert orch._calculate_historical_atm("2026-01-05") is None

    def test_nifty_candles_exist_but_not_for_this_expiry(self, db):
        """Candles exist for other dates but not the target expiry."""
        _add_nifty_candle(db, date(2026, 1, 2), 25000.0)
        _add_spec(db, "IK_25000", "2026-01-10", 25000, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        assert orch._calculate_historical_atm("2026-01-10") is None

    def test_no_strikes_for_expiry(self, db):
        """NIFTY candles exist but no contract specs for this expiry."""
        _add_nifty_candle(db, date(2026, 1, 5), 25000.0)

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        assert orch._calculate_historical_atm("2026-01-05") is None

    def test_invalid_expiry_format(self, db):
        """Invalid expiry string returns None gracefully."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        assert orch._calculate_historical_atm("not-a-date") is None

    def test_filter_by_universe_skips_missing_expiries(self, db):
        """_filter_by_universe should skip expiries with no NIFTY data
        rather than crashing."""
        # Only add NIFTY candles for 2026-06-01
        _add_nifty_candle(db, date(2026, 6, 1), 24000.0)

        # Add specs for two expiries: one with data, one without
        for s in [23950, 24000, 24050]:
            _add_spec(db, f"IK_{s}_JUN", "2026-06-01", s, "CE")
        for s in [22000, 22050, 22100]:
            _add_spec(db, f"IK_{s}_JAN", "2026-01-05", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.underlying == "NIFTY")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_10")
        # Only the June expiry should be selected
        assert all(s.expiry == "2026-06-01" for s in filtered)
        assert len(filtered) > 0


# ===========================================================================
# 5. INCOMPLETE HISTORICAL COVERAGE
# ===========================================================================


class TestIncompleteHistoricalCoverage:
    """Tests for when NIFTY data coverage is partial."""

    def test_multi_expiry_partial_coverage(self, db):
        """Only expiries with NIFTY data on their expiry date are included."""
        # Candle for 2026-03-02 and 2026-06-01 only
        _add_nifty_candle(db, date(2026, 3, 2), 24659.25)
        _add_nifty_candle(db, date(2026, 6, 1), 24000.0)

        # Specs for 3 expiries
        for s in [24600, 24650, 24700]:
            _add_spec(db, f"IK_{s}_MAR", "2026-03-02", s, "CE")
        for s in [24000, 24050, 24100]:
            _add_spec(db, f"IK_{s}_JUN", "2026-06-01", s, "CE")
        for s in [23000, 23050, 23100]:
            _add_spec(db, f"IK_{s}_APR", "2026-04-07", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(ContractSpec.underlying == "NIFTY")
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_10")

        expiries_included = set(s.expiry for s in filtered)
        assert "2026-03-02" in expiries_included
        assert "2026-06-01" in expiries_included
        assert "2026-04-07" not in expiries_included

    def test_atm_still_correct_with_partial_data(self, db):
        """ATM for each expiry is independently correct."""
        _add_nifty_candle(db, date(2026, 3, 2), 24659.25)
        _add_nifty_candle(db, date(2026, 6, 1), 24000.0)

        for s in [24600, 24650, 24700]:
            _add_spec(db, f"IK_{s}_MAR", "2026-03-02", s, "CE")
        for s in [23950, 24000, 24050]:
            _add_spec(db, f"IK_{s}_JUN", "2026-06-01", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        atm_mar = orch._calculate_historical_atm("2026-03-02")
        atm_jun = orch._calculate_historical_atm("2026-06-01")

        assert atm_mar == 24650  # from 24659.25
        assert atm_jun == 24000  # from 24000.0

    def test_nifty_backfill_default_covers_registry(self, db):
        """run_nifty() without start_date should auto-compute from the
        earliest expiry in the contract registry."""
        # Add a contract with an old expiry
        _add_spec(db, "IK_OLD", "2024-10-03", 25000, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_nifty())
        loop.close()

        # The chunks should start from 2024-09-30 (3 days before 2024-10-03)
        assert result.status == "DRY_RUN"
        chunks = result.metadata["chunks"]
        assert len(chunks) > 0
        first_chunk_from = chunks[0]["from"]
        assert first_chunk_from == "2024-09-30", (
            f"Expected first chunk from 2024-09-30, got {first_chunk_from}"
        )

    def test_nifty_backfill_with_custom_start_date(self, db):
        """run_nifty(start_date=...) should respect the override."""
        _add_spec(db, "IK_OLD", "2024-10-03", 25000, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(
            orch.run_nifty(start_date=date(2025, 1, 1))
        )
        loop.close()

        chunks = result.metadata["chunks"]
        first_chunk_from = chunks[0]["from"]
        assert first_chunk_from == "2025-01-01", (
            f"Expected custom start 2025-01-01, got {first_chunk_from}"
        )

    def test_nifty_backfill_empty_registry_fallback(self, db):
        """With no contracts in registry, default falls back to 365 days ago."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_nifty())
        loop.close()

        chunks = result.metadata["chunks"]
        today = datetime.now(timezone.utc).date()
        expected_start = today - timedelta(days=365)
        first_chunk_from = chunks[0]["from"]
        assert first_chunk_from == str(expected_start), (
            f"Expected fallback start {expected_start}, got {first_chunk_from}"
        )


# ===========================================================================
# 6. ATM + UNIVERSE INTEGRATION
# ===========================================================================


class TestATMUniverseIntegration:
    """Integration tests: ATM fix applied to full universe selection flow."""

    def test_atm_10_with_correct_opening_candle(self, db):
        """ATM_10 universe selection should use the correct ATM from
        the expiry-day opening candle."""
        _add_nifty_candle(db, date(2026, 3, 2), 24659.25)  # expiry day
        _add_nifty_candle(db, date(2026, 3, 1), 25169.80)  # prev day

        strikes = [24600 + i * 50 for i in range(-15, 16)]
        for s in strikes:
            _add_spec(db, f"IK_{s}_CE", "2026-03-02", s, "CE")
            _add_spec(db, f"IK_{s}_PE", "2026-03-02", s, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(
                ContractSpec.expiry == "2026-03-02"
            )
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_10")

        # ATM = 24650 (from open 24659.25)
        # Range: 24650 ± 10 strikes → 24150 to 25150
        strikes_selected = sorted(set(s.strike_price for s in filtered))
        assert 24650 in strikes_selected
        assert 25150 in strikes_selected
        assert 24150 in strikes_selected
        # 25200 (old ATM if using prev close) should NOT be in range
        assert 25200 not in strikes_selected

    def test_ce_pe_symmetry_after_fix(self, db):
        """Both CE and PE should be symmetric around the corrected ATM."""
        _add_nifty_candle(db, date(2026, 6, 1), 24000.0)

        strikes = [24000 + i * 50 for i in range(-15, 16)]
        for s in strikes:
            _add_spec(db, f"IK_{s}_CE", "2026-06-01", s, "CE")
            _add_spec(db, f"IK_{s}_PE", "2026-06-01", s, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)
        specs = db.execute(
            select(ContractSpec).where(
                ContractSpec.expiry == "2026-06-01"
            )
        ).scalars().all()

        filtered = orch._filter_by_universe(specs, "ATM_10")
        ce_count = sum(1 for s in filtered if s.instrument_type == "CE")
        pe_count = sum(1 for s in filtered if s.instrument_type == "PE")
        assert ce_count == pe_count

    def test_atm_change_across_consecutive_expiries(self, db):
        """Different expiries with different NIFTY opens should produce
        different ATMs."""
        _add_nifty_candle(db, date(2026, 3, 2), 24659.25)
        _add_nifty_candle(db, date(2026, 3, 9), 23500.00)

        for s in [24600, 24650, 24700]:
            _add_spec(db, f"IK_{s}_W1", "2026-03-02", s, "CE")
        for s in [23450, 23500, 23550]:
            _add_spec(db, f"IK_{s}_W2", "2026-03-09", s, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        atm_w1 = orch._calculate_historical_atm("2026-03-02")
        atm_w2 = orch._calculate_historical_atm("2026-03-09")

        assert atm_w1 == 24650
        assert atm_w2 == 23500
        assert atm_w1 != atm_w2
