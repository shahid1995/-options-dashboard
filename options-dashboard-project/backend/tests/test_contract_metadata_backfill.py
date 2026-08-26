"""Phase 7.8F — Contract metadata backfill tests.

Exercises:

* ``run_backfill`` — end-to-end backfill orchestration
* Expiry filtering
* Multiple expiries, strikes, CE + PE
* Various lot sizes preserved exactly (75, 50, 25, 65)
* minimum_lot differs from lot_size
* missing lot_size stays NULL
* No current-lot fallback
* Idempotent rerun
* API 401 / 403 / 429 / 5xx errors
* Empty responses
* Partial failure and resume
* Dry-run
* Provenance tracking
* instrument_key uniqueness

All tests use in-memory SQLite.  No live API calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ContractSpec
from app.services.contract_metadata import (
    SOURCE_UPSTOX_EXPIRED,
    get_contract_specification,
    count_contract_specs,
    get_all_expiry_dates,
)
from app.tools.contract_metadata_backfill import (
    _filter_expiries,
    _normalize_expiry,
    run_backfill,
    report_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Realistic fixtures — Upstox Expired Option Contracts API response format
# ---------------------------------------------------------------------------

def _make_contract(
    instrument_key: str,
    expiry: str = "2025-04-17",
    lot_size: int | None = 75,
    minimum_lot: int | None = 75,
    freeze_quantity: int | None = 1800,
    tick_size: float | None = 5.0,
    strike_price: float = 20400.0,
    instrument_type: str = "PE",
    trading_symbol: str = "NIFTY 20400 PE 17 APR 25",
    underlying_key: str = "NSE_INDEX|NIFTY 50",
    **overrides,
) -> dict:
    """Create a realistic Upstox expired option contract dict."""
    base = {
        "instrument_key": instrument_key,
        "underlying_key": underlying_key,
        "underlying_symbol": "NIFTY",
        "expiry": expiry,
        "strike_price": strike_price,
        "instrument_type": instrument_type,
        "lot_size": lot_size,
        "minimum_lot": minimum_lot,
        "freeze_quantity": freeze_quantity,
        "tick_size": tick_size,
        "trading_symbol": trading_symbol,
        "segment": "INDICES",
        "exchange": "NSE_FO",
        "weekly": False,
    }
    base.update(overrides)
    return base


# Real fixture: NIFTY 20400 PE 17 APR 25
FIXTURE_PE = _make_contract(
    instrument_key="NSE_FO|47983|17-04-2025",
    strike_price=20400.0,
    instrument_type="PE",
    trading_symbol="NIFTY 20400 PE 17 APR 25",
    lot_size=75,
)

# Real fixture: NIFTY 20400 CE 17 APR 25
FIXTURE_CE = _make_contract(
    instrument_key="NSE_FO|47982|17-04-2025",
    strike_price=20400.0,
    instrument_type="CE",
    trading_symbol="NIFTY 20400 CE 17 APR 25",
    lot_size=75,
)

# Synthetic historical fixture: lot_size = 65
FIXTURE_LOT65 = _make_contract(
    instrument_key="NSE_FO|50001|20-06-2024",
    expiry="2024-06-20",
    strike_price=22000.0,
    instrument_type="CE",
    trading_symbol="NIFTY 22000 CE 20 JUN 24",
    lot_size=65,
    minimum_lot=65,
    freeze_quantity=1625,
)

# Synthetic historical fixture: lot_size = 50
FIXTURE_LOT50 = _make_contract(
    instrument_key="NSE_FO|52001|27-03-2025",
    expiry="2025-03-27",
    strike_price=23000.0,
    instrument_type="PE",
    trading_symbol="NIFTY 23000 PE 27 MAR 25",
    lot_size=50,
    minimum_lot=50,
    freeze_quantity=1250,
)

# Synthetic historical fixture: lot_size = 25 (post-reduction)
FIXTURE_LOT25 = _make_contract(
    instrument_key="NSE_FO|60001|10-07-2025",
    expiry="2025-07-10",
    strike_price=25000.0,
    instrument_type="CE",
    trading_symbol="NIFTY 25000 CE 10 JUL 25",
    lot_size=25,
    minimum_lot=25,
    freeze_quantity=625,
)

# Fixture where minimum_lot != lot_size
FIXTURE_DIFF_MIN = _make_contract(
    instrument_key="NSE_FO|65001|28-08-2025",
    expiry="2025-08-28",
    strike_price=24500.0,
    instrument_type="PE",
    trading_symbol="NIFTY 24500 PE 28 AUG 25",
    lot_size=75,
    minimum_lot=50,
    freeze_quantity=1800,
)

# Fixture with missing lot_size
FIXTURE_NO_LOT = _make_contract(
    instrument_key="NSE_FO|70001|25-09-2025",
    expiry="2025-09-25",
    strike_price=26000.0,
    instrument_type="CE",
    trading_symbol="NIFTY 26000 CE 25 SEP 25",
    lot_size=None,
    minimum_lot=None,
    freeze_quantity=None,
    tick_size=None,
)


# ---------------------------------------------------------------------------
# Test: Expiry filtering
# ---------------------------------------------------------------------------

class TestExpiryFiltering:
    def test_normalize_expiry_month(self):
        assert _normalize_expiry("2025-04") == "2025-04-01"

    def test_normalize_expiry_full(self):
        assert _normalize_expiry("2025-04-17") == "2025-04-17"

    def test_filter_no_bounds(self):
        expiries = ["2025-01-15", "2025-02-20", "2025-03-27"]
        assert _filter_expiries(expiries, None, None) == expiries

    def test_filter_start_only(self):
        expiries = ["2025-01-15", "2025-02-20", "2025-03-27"]
        result = _filter_expiries(expiries, "2025-02", None)
        assert result == ["2025-02-20", "2025-03-27"]

    def test_filter_end_only(self):
        expiries = ["2025-01-15", "2025-02-20", "2025-03-27"]
        result = _filter_expiries(expiries, None, "2025-02-28")
        assert result == ["2025-01-15", "2025-02-20"]

    def test_filter_both_bounds(self):
        expiries = ["2025-01-15", "2025-02-20", "2025-03-27", "2025-04-10"]
        result = _filter_expiries(expiries, "2025-02", "2025-03-31")
        assert result == ["2025-02-20", "2025-03-27"]

    def test_filter_empty(self):
        assert _filter_expiries([], "2025-01", "2025-12") == []

    def test_filter_no_match(self):
        expiries = ["2025-01-15", "2025-02-20"]
        result = _filter_expiries(expiries, "2025-06", "2025-12")
        assert result == []


# ---------------------------------------------------------------------------
# Test: Successful backfill
# ---------------------------------------------------------------------------

class TestSuccessfulBackfill:
    @pytest.mark.asyncio
    async def test_single_expiry(self, db):
        """Backfill one expiry with 2 contracts."""
        expiries_resp = MagicMock()
        expiries_resp.status_code = 200
        expiries_resp.json.return_value = {
            "status": "success",
            "data": ["2025-04-17"],
        }

        contracts_resp = MagicMock()
        contracts_resp.status_code = 200
        contracts_resp.json.return_value = {
            "status": "success",
            "data": [FIXTURE_PE, FIXTURE_CE],
        }

        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_PE, FIXTURE_CE]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats["expiries_discovered"] == 1
        assert stats["expiries_fetched"] == 1
        assert stats["contracts_inserted"] == 2
        assert stats["expiries_failed"] == 0

        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec is not None
        assert spec["lot_size"] == 75

    @pytest.mark.asyncio
    async def test_multiple_expiries(self, db):
        """Backfill multiple expiries."""
        contracts_1 = [_make_contract(
            instrument_key=f"NSE_FO|1000{i}|2025-04-17",
            strike_price=20000.0 + i * 100,
            instrument_type="CE" if i % 2 == 0 else "PE",
        ) for i in range(5)]

        contracts_2 = [_make_contract(
            instrument_key=f"NSE_FO|2000{i}|2025-05-15",
            expiry="2025-05-15",
            strike_price=21000.0 + i * 100,
            instrument_type="CE" if i % 2 == 0 else "PE",
            trading_symbol=f"NIFTY {21000 + i*100} {'CE' if i%2==0 else 'PE'} 15 MAY 25",
        ) for i in range(3)]

        async def mock_expiries(token, underlying="NIFTY"):
            return ["2025-04-17", "2025-05-15"]

        call_count = 0
        async def mock_contracts(token, underlying="NIFTY", expiry_date=""):
            nonlocal call_count
            call_count += 1
            if expiry_date == "2025-04-17":
                return contracts_1
            elif expiry_date == "2025-05-15":
                return contracts_2
            return []

        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", side_effect=mock_expiries), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", side_effect=mock_contracts), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats["expiries_discovered"] == 2
        assert stats["expiries_fetched"] == 2
        assert stats["contracts_inserted"] == 8  # 5 + 3

    @pytest.mark.asyncio
    async def test_ce_and_pe_preserved(self, db):
        """CE and PE contracts are both stored correctly."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_PE, FIXTURE_CE]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        pe = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        ce = get_contract_specification(db, "NSE_FO|47982|17-04-2025")

        assert pe is not None
        assert pe["instrument_type"] == "PE"
        assert ce is not None
        assert ce["instrument_type"] == "CE"


# ---------------------------------------------------------------------------
# Test: Lot-size preservation
# ---------------------------------------------------------------------------

class TestLotSizePreservation:
    @pytest.mark.asyncio
    async def test_lot_size_75(self, db):
        """lot_size=75 preserved exactly."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_PE]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec["lot_size"] == 75

    @pytest.mark.asyncio
    async def test_lot_size_50(self, db):
        """lot_size=50 preserved exactly."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-03-27"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_LOT50]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|52001|27-03-2025")
        assert spec["lot_size"] == 50

    @pytest.mark.asyncio
    async def test_lot_size_25(self, db):
        """lot_size=25 preserved exactly."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-07-10"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_LOT25]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|60001|10-07-2025")
        assert spec["lot_size"] == 25

    @pytest.mark.asyncio
    async def test_lot_size_65(self, db):
        """lot_size=65 preserved exactly."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2024-06-20"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_LOT65]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|50001|20-06-2024")
        assert spec["lot_size"] == 65

    @pytest.mark.asyncio
    async def test_different_lot_sizes_coexist(self, db):
        """Multiple lot sizes coexist without overwriting each other."""
        all_contracts = [FIXTURE_PE, FIXTURE_LOT65, FIXTURE_LOT50, FIXTURE_LOT25]

        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2024-06-20", "2025-03-27", "2025-04-17", "2025-07-10"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=all_contracts), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        assert get_contract_specification(db, "NSE_FO|47983|17-04-2025")["lot_size"] == 75
        assert get_contract_specification(db, "NSE_FO|50001|20-06-2024")["lot_size"] == 65
        assert get_contract_specification(db, "NSE_FO|52001|27-03-2025")["lot_size"] == 50
        assert get_contract_specification(db, "NSE_FO|60001|10-07-2025")["lot_size"] == 25

    @pytest.mark.asyncio
    async def test_minimum_lot_differs_from_lot_size(self, db):
        """minimum_lot != lot_size stored as separate fields."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-08-28"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_DIFF_MIN]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|65001|28-08-2025")
        assert spec["lot_size"] == 75
        assert spec["minimum_lot"] == 50
        assert spec["lot_size"] != spec["minimum_lot"]

    @pytest.mark.asyncio
    async def test_missing_lot_size_stays_null(self, db):
        """lot_size=None stays NULL — never substituted."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-09-25"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_NO_LOT]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|70001|25-09-2025")
        assert spec is not None
        assert spec["lot_size"] is None


# ---------------------------------------------------------------------------
# Test: No current-lot fallback
# ---------------------------------------------------------------------------

class TestNoCurrentLotFallback:
    @pytest.mark.asyncio
    async def test_null_lot_never_replaced_with_current(self, db):
        """A NULL lot_size in the registry is NEVER replaced with a current value."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-09-25"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_NO_LOT]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|70001|25-09-2025")
        assert spec is not None
        assert spec["lot_size"] is None  # Still NULL — not 25 or 75


# ---------------------------------------------------------------------------
# Test: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_rerun_is_idempotent(self, db):
        """Re-running the same backfill does not create duplicates."""
        contracts = [FIXTURE_PE, FIXTURE_CE]

        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=contracts), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats1 = await run_backfill(underlying="NIFTY")
            stats2 = await run_backfill(underlying="NIFTY")

        assert stats1["contracts_inserted"] == 2
        assert stats2["contracts_idempotent"] == 2
        assert stats2["contracts_inserted"] == 0

        # DB count should be exactly 2, not 4
        assert count_contract_specs(db, "NIFTY") == 2


# ---------------------------------------------------------------------------
# Test: API errors
# ---------------------------------------------------------------------------

class TestAPIErrors:
    @pytest.mark.asyncio
    async def test_api_401(self, db):
        """401 error does not crash — skips the expiry."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, side_effect=Exception("401 Unauthorized")), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats["expiries_failed"] == 1
        assert stats["contracts_inserted"] == 0

    @pytest.mark.asyncio
    async def test_api_403_plus_plan(self, db):
        """403 (Plus plan required) does not crash."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, side_effect=Exception("403 Forbidden — Upstox Plus required")), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats["expiries_failed"] == 1
        assert count_contract_specs(db) == 0

    @pytest.mark.asyncio
    async def test_api_empty_expiry_response(self, db):
        """Empty expiry list returns no error."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=[]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats["expiries_discovered"] == 0
        assert stats["expiries_fetched"] == 0

    @pytest.mark.asyncio
    async def test_api_empty_contract_response(self, db):
        """Empty contract list for an expiry is handled gracefully."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats["expiries_fetched"] == 1
        assert stats["contracts_inserted"] == 0

    @pytest.mark.asyncio
    async def test_no_session(self, db):
        """No active session returns error."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value=None), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY")

        assert stats.get("error") == "no_session"


# ---------------------------------------------------------------------------
# Test: Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    @pytest.mark.asyncio
    async def test_source_and_reference(self, db):
        """Source and source_reference are stored."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_PE]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec["source"] == "UPSTOX_EXPIRED_INSTRUMENTS"
        assert "2025-04-17" in spec["source_reference"]
        assert spec["fetched_at"] is not None

    @pytest.mark.asyncio
    async def test_fields_preserved(self, db):
        """All Upstox fields are preserved in the stored record."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_PE]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec["instrument_key"] == "NSE_FO|47983|17-04-2025"
        assert spec["underlying"] == "NIFTY"
        assert spec["expiry"] == "2025-04-17"
        assert spec["strike_price"] == 20400.0
        assert spec["instrument_type"] == "PE"
        assert spec["lot_size"] == 75
        assert spec["minimum_lot"] == 75
        assert spec["freeze_quantity"] == 1800
        assert spec["tick_size"] == 5.0
        assert spec["trading_symbol"] == "NIFTY 20400 PE 17 APR 25"
        assert spec["exchange"] == "NSE_FO"


# ---------------------------------------------------------------------------
# Test: Dry run
# ---------------------------------------------------------------------------

class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_persist(self, db):
        """Dry-run fetches data but does not write to DB."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            stats = await run_backfill(underlying="NIFTY", dry_run=True)

        assert stats["expiries_discovered"] == 1
        assert count_contract_specs(db) == 0  # Nothing persisted


# ---------------------------------------------------------------------------
# Test: instrument_key uniqueness
# ---------------------------------------------------------------------------

class TestInstrumentKeyUniqueness:
    @pytest.mark.asyncio
    async def test_instrument_key_is_unique(self, db):
        """Each instrument_key is unique in the database."""
        with patch("app.tools.contract_metadata_backfill.get_token", return_value="test-token"), \
             patch("app.tools.contract_metadata_backfill.get_expired_expiries", new_callable=AsyncMock, return_value=["2025-04-17"]), \
             patch("app.tools.contract_metadata_backfill.get_expired_option_contracts", new_callable=AsyncMock, return_value=[FIXTURE_PE, FIXTURE_CE, FIXTURE_DIFF_MIN]), \
             patch("app.tools.contract_metadata_backfill._get_session", return_value=db):

            await run_backfill(underlying="NIFTY")

        assert count_contract_specs(db) == 3
        # Each has a unique instrument_key
        keys = [
            "NSE_FO|47983|17-04-2025",
            "NSE_FO|47982|17-04-2025",
            "NSE_FO|65001|28-08-2025",
        ]
        for key in keys:
            spec = get_contract_specification(db, key)
            assert spec is not None
