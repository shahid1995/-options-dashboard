"""Phase 7.8 — Contract metadata registry tests.

Exercises the full lifecycle of the contract-metadata layer:

* ``get_contract_specification``  — lookup by instrument_key
* ``upsert_contract_spec``        — insert / idempotent / conflict / fill
* ``upsert_contract_specs``       — batch insert
* Query helpers                   — count, expiry dates

All tests use an in-memory SQLite database.  No live API calls.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ContractSpec
from app.services.contract_metadata import (
    SOURCE_UPSTOX_EXPIRED,
    UpsertResult,
    count_contract_specs,
    get_all_expiry_dates,
    get_contract_specification,
    upsert_contract_spec,
    upsert_contract_specs,
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


# Realistic Upstox API response fixture — NIFTY 20400 PE 17 APR 25
FIXTURE_PE_20400 = {
    "name": "NIFTY",
    "segment": "NSE_FO",
    "exchange": "NSE",
    "expiry": "2025-04-17",
    "instrument_key": "NSE_FO|47983|17-04-2025",
    "exchange_token": "47983",
    "trading_symbol": "NIFTY 20400 PE 17 APR 25",
    "tick_size": 5,
    "lot_size": 75,
    "instrument_type": "PE",
    "freeze_quantity": 1800,
    "underlying_key": "NSE_INDEX|Nifty 50",
    "underlying_type": "INDEX",
    "underlying_symbol": "NIFTY",
    "strike_price": 20400,
    "minimum_lot": 75,
    "weekly": True,
}

# NIFTY 20400 CE 17 APR 25
FIXTURE_CE_20400 = {
    **FIXTURE_PE_20400,
    "instrument_key": "NSE_FO|47982|17-04-2025",
    "trading_symbol": "NIFTY 20400 CE 17 APR 25",
    "instrument_type": "CE",
}

# Synthetic historical fixtures with different lot sizes
# (NOT claimed to correspond to real NSE effective dates)
FIXTURE_LOT_65 = {
    **FIXTURE_PE_20400,
    "instrument_key": "NSE_FO|99965|17-04-2025",
    "trading_symbol": "NIFTY 25000 PE 17 APR 25 (synthetic lot=65)",
    "lot_size": 65,
    "minimum_lot": 65,
    "strike_price": 25000,
}

FIXTURE_LOT_50 = {
    **FIXTURE_PE_20400,
    "instrument_key": "NSE_FO|99950|17-04-2025",
    "trading_symbol": "NIFTY 25000 PE 17 APR 25 (synthetic lot=50)",
    "lot_size": 50,
    "minimum_lot": 50,
    "strike_price": 25000,
}

FIXTURE_LOT_25 = {
    **FIXTURE_PE_20400,
    "instrument_key": "NSE_FO|99925|17-04-2025",
    "trading_symbol": "NIFTY 25000 PE 17 APR 25 (synthetic lot=25)",
    "lot_size": 25,
    "minimum_lot": 25,
    "strike_price": 25000,
}


# ===================================================================
# 1. lot_size preservation — various historical values
# ===================================================================


class TestLotSizePreservation:
    """Verify that the system preserves whatever lot_size the API returns."""

    def test_lot_size_75_preserved(self):
        spec = get_contract_specification(db := _fresh_db(), FIXTURE_PE_20400["instrument_key"])
        assert spec is None
        upsert_contract_spec(db, FIXTURE_PE_20400)
        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])
        assert spec is not None
        assert spec["lot_size"] == 75

    def test_lot_size_65_preserved(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_LOT_65)
        spec = get_contract_specification(db, FIXTURE_LOT_65["instrument_key"])
        assert spec["lot_size"] == 65

    def test_lot_size_50_preserved(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_LOT_50)
        spec = get_contract_specification(db, FIXTURE_LOT_50["instrument_key"])
        assert spec["lot_size"] == 50

    def test_lot_size_25_preserved(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_LOT_25)
        spec = get_contract_specification(db, FIXTURE_LOT_25["instrument_key"])
        assert spec["lot_size"] == 25


# ===================================================================
# 2. minimum_lot stored separately
# ===================================================================


class TestMinimumLotSeparate:
    """lot_size and minimum_lot are stored separately — never assumed equal."""

    def test_minimum_lot_differs_from_lot_size(self):
        db = _fresh_db()
        contract = {**FIXTURE_PE_20400, "lot_size": 75, "minimum_lot": 1}
        upsert_contract_spec(db, contract)
        spec = get_contract_specification(db, contract["instrument_key"])
        assert spec["lot_size"] == 75
        assert spec["minimum_lot"] == 1


# ===================================================================
# 3. Missing lot_size remains NULL
# ===================================================================


class TestMissingLotSize:
    """When lot_size is absent from the API response, it stays NULL."""

    def test_missing_lot_size_stays_none(self):
        db = _fresh_db()
        contract = {**FIXTURE_PE_20400, "lot_size": None, "minimum_lot": None}
        upsert_contract_spec(db, contract)
        spec = get_contract_specification(db, contract["instrument_key"])
        assert spec["lot_size"] is None
        assert spec["minimum_lot"] is None


# ===================================================================
# 4. Current lot size is never substituted
# ===================================================================


class TestNoCurrentLotSubstitution:
    """The system must NEVER substitute today's lot size for historical lot_size."""

    def test_none_lot_size_not_replaced_by_current(self):
        db = _fresh_db()
        # Insert with NULL lot_size
        contract = {**FIXTURE_PE_20400, "lot_size": None}
        upsert_contract_spec(db, contract)
        # Re-upsert with valid lot_size — should fill it
        contract2 = {**FIXTURE_PE_20400, "lot_size": 75}
        result = upsert_contract_spec(db, contract2)
        assert result.action == "filled_lot_size"
        # Verify it's 75, NOT 25 (current lot size)
        spec = get_contract_specification(db, contract["instrument_key"])
        assert spec["lot_size"] == 75


# ===================================================================
# 5. Unknown instrument returns None
# ===================================================================


class TestUnknownInstrument:
    """Lookup for a non-existent instrument_key returns None."""

    def test_unknown_returns_none(self):
        db = _fresh_db()
        spec = get_contract_specification(db, "NSE_FO|000000|01-01-2099")
        assert spec is None


# ===================================================================
# 6. Idempotency
# ===================================================================


class TestIdempotency:
    """Same instrument_key + same metadata → idempotent no-op."""

    def test_same_data_is_idempotent(self):
        db = _fresh_db()
        r1 = upsert_contract_spec(db, FIXTURE_PE_20400)
        assert r1.action == "inserted"

        r2 = upsert_contract_spec(db, FIXTURE_PE_20400)
        assert r2.action == "idempotent"
        assert r2.lot_size == 75

        # Count is still 1
        assert count_contract_specs(db) == 1


# ===================================================================
# 7. Existing valid lot_size is NOT overwritten
# ===================================================================


class TestImmutability:
    """Once a valid lot_size is stored, it is NEVER overwritten."""

    def test_conflict_preserves_existing_lot_size(self):
        db = _fresh_db()
        # Insert with lot_size=75
        upsert_contract_spec(db, FIXTURE_PE_20400)

        # Attempt to overwrite with lot_size=25
        conflicting = {**FIXTURE_PE_20400, "lot_size": 25, "minimum_lot": 25}
        result = upsert_contract_spec(db, conflicting)

        assert result.action == "conflict"
        assert result.lot_size == 75  # existing value preserved
        assert "CONFLICT" in result.message

        # Verify DB still has 75
        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])
        assert spec["lot_size"] == 75

    def test_same_lot_size_is_idempotent(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_PE_20400)
        result = upsert_contract_spec(db, FIXTURE_PE_20400)
        assert result.action == "idempotent"

    def test_fill_null_lot_size(self):
        db = _fresh_db()
        # Insert with NULL lot_size
        contract_null = {**FIXTURE_PE_20400, "lot_size": None, "minimum_lot": None}
        upsert_contract_spec(db, contract_null)

        # Fill with valid lot_size
        result = upsert_contract_spec(db, FIXTURE_PE_20400)
        assert result.action == "filled_lot_size"
        assert result.lot_size == 75

        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])
        assert spec["lot_size"] == 75


# ===================================================================
# 8. Candle normalization contains no lot_size
# ===================================================================


class TestCandleNormalizationLotSizeFree:
    """Candle normalization is completely independent of lot_size."""

    def test_normalized_candle_has_no_lot_size(self):
        from app.services.candle_ingestion import normalize_candle

        raw = ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0]
        result = normalize_candle(raw)
        assert result is not None
        for key in ("lot_size", "minimum_lot", "freeze_quantity", "tick_size", "instrument_key"):
            assert key not in result


# ===================================================================
# 9. Candle ingestion succeeds without contract metadata
# ===================================================================


class TestCandleIngestionIndependent:
    """Candle ingestion never fails because contract metadata is missing."""

    def test_candle_ingestion_works_without_registry(self):
        from app.services.candle_ingestion import extract_candles_from_response, normalize_candles

        response = {
            "status": "success",
            "data": {
                "candles": [
                    ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000, 0],
                ]
            },
        }

        raw = extract_candles_from_response(response)
        normalized = normalize_candles(raw)
        assert len(normalized) == 1
        assert normalized[0]["open"] == 25500.0

        # No contract metadata exists — candle ingestion is unaffected
        db = _fresh_db()
        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec is None  # missing metadata — but candle ingestion worked fine


# ===================================================================
# 10. Expired API 401/403 does not break candle ingestion
# ===================================================================


class TestExpiredApiUnavailable:
    """When the Expired Option Contracts API is unavailable, the system degrades safely."""

    def test_api_401_does_not_affect_candles(self):
        from app.services.candle_ingestion import normalize_candles

        # Simulate: expired API returns 401 → no contract metadata
        db = _fresh_db()
        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec is None

        # Candle pipeline continues independently
        candles = normalize_candles([
            ["2026-08-22T15:27:00+05:30", 25500.0, 25520.0, 25480.0, 25510.0, 15000],
        ])
        assert len(candles) == 1

    def test_api_403_plus_plan_required(self):
        """UDAPI1149 = Upstox Plus plan required — system degrades safely."""
        db = _fresh_db()
        # No contracts stored — equivalent to API returning 403
        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")
        assert spec is None

    def test_api_empty_response(self):
        """Empty API response — no contracts stored, system continues."""
        db = _fresh_db()
        results = upsert_contract_specs(db, [])
        assert results == []
        assert count_contract_specs(db) == 0


# ===================================================================
# 11. instrument_key is the lookup identity
# ===================================================================


class TestInstrumentKeyIdentity:
    """instrument_key is the unique identity — not expiry/strike/type."""

    def test_different_keys_different_specs(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_PE_20400)
        upsert_contract_spec(db, FIXTURE_CE_20400)

        assert count_contract_specs(db) == 2

        pe = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])
        ce = get_contract_specification(db, FIXTURE_CE_20400["instrument_key"])

        assert pe["instrument_type"] == "PE"
        assert ce["instrument_type"] == "CE"
        assert pe["instrument_key"] != ce["instrument_key"]


# ===================================================================
# 12. expiry/strike/type are preserved
# ===================================================================


class TestContractFieldsPreserved:
    """All contract fields from Upstox API are preserved."""

    def test_all_fields_preserved(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_PE_20400)
        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])

        assert spec["instrument_key"] == "NSE_FO|47983|17-04-2025"
        assert spec["expiry"] == "2025-04-17"
        assert spec["strike_price"] == 20400.0
        assert spec["instrument_type"] == "PE"
        assert spec["lot_size"] == 75
        assert spec["minimum_lot"] == 75
        assert spec["freeze_quantity"] == 1800
        assert spec["tick_size"] == 5.0
        assert spec["trading_symbol"] == "NIFTY 20400 PE 17 APR 25"
        assert spec["segment"] == "NSE_FO"
        assert spec["exchange"] == "NSE"
        assert spec["weekly"] is True
        assert spec["underlying_key"] == "NSE_INDEX|Nifty 50"
        assert spec["underlying"] == "NIFTY"


# ===================================================================
# 13. source/source_reference are preserved
# ===================================================================


class TestProvenance:
    """Every row traces back to its source."""

    def test_source_and_reference_stored(self):
        db = _fresh_db()
        upsert_contract_spec(
            db, FIXTURE_PE_20400,
            source="UPSTOX_EXPIRED_INSTRUMENTS",
            source_reference="GET /v2/expired-instruments/option/contract?instrument_key=NSE_INDEX|Nifty 50&expiry_date=2025-04-17",
        )
        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])

        assert spec["source"] == "UPSTOX_EXPIRED_INSTRUMENTS"
        assert "GET /v2/expired-instruments" in spec["source_reference"]
        assert spec["fetched_at"] is not None


# ===================================================================
# 14. Batch upsert
# ===================================================================


class TestBatchUpsert:
    """Batch upsert inserts multiple contracts."""

    def test_batch_insert(self):
        db = _fresh_db()
        contracts = [FIXTURE_PE_20400, FIXTURE_CE_20400, FIXTURE_LOT_65, FIXTURE_LOT_25]
        results = upsert_contract_specs(db, contracts)

        assert len(results) == 4
        assert all(r.action == "inserted" for r in results)
        assert count_contract_specs(db) == 4

    def test_batch_idempotent(self):
        db = _fresh_db()
        contracts = [FIXTURE_PE_20400, FIXTURE_CE_20400]
        upsert_contract_specs(db, contracts)
        results = upsert_contract_specs(db, contracts)
        assert all(r.action == "idempotent" for r in results)
        assert count_contract_specs(db) == 2


# ===================================================================
# 15. Query helpers
# ===================================================================


class TestQueryHelpers:
    """Count and expiry-date queries."""

    def test_count_empty(self):
        db = _fresh_db()
        assert count_contract_specs(db) == 0

    def test_count_with_data(self):
        db = _fresh_db()
        upsert_contract_specs(db, [FIXTURE_PE_20400, FIXTURE_CE_20400])
        assert count_contract_specs(db) == 2

    def test_count_by_underlying(self):
        db = _fresh_db()
        upsert_contract_specs(db, [FIXTURE_PE_20400, FIXTURE_CE_20400])
        assert count_contract_specs(db, underlying="NIFTY") == 2
        assert count_contract_specs(db, underlying="BANKNIFTY") == 0

    def test_expiry_dates(self):
        db = _fresh_db()
        upsert_contract_specs(db, [FIXTURE_PE_20400, FIXTURE_CE_20400])
        dates = get_all_expiry_dates(db)
        assert dates == ["2025-04-17"]


# ===================================================================
# 16. Missing instrument_key in contract dict
# ===================================================================


class TestMissingInstrumentKey:
    def test_missing_key_returns_error(self):
        db = _fresh_db()
        result = upsert_contract_spec(db, {"lot_size": 75})
        assert result.action == "error"
        assert "instrument_key" in result.message


# ===================================================================
# 17. Multiple different lot sizes in registry
# ===================================================================


class TestMultipleLotSizes:
    """Different historical contracts can contain different lot sizes."""

    def test_different_lot_sizes_coexist(self):
        db = _fresh_db()
        upsert_contract_specs(db, [
            FIXTURE_LOT_75 := {**FIXTURE_PE_20400, "lot_size": 75, "minimum_lot": 75},
            FIXTURE_LOT_65,
            FIXTURE_LOT_50,
            FIXTURE_LOT_25,
        ])

        spec_75 = get_contract_specification(db, FIXTURE_LOT_75["instrument_key"])
        spec_65 = get_contract_specification(db, FIXTURE_LOT_65["instrument_key"])
        spec_50 = get_contract_specification(db, FIXTURE_LOT_50["instrument_key"])
        spec_25 = get_contract_specification(db, FIXTURE_LOT_25["instrument_key"])

        assert spec_75["lot_size"] == 75
        assert spec_65["lot_size"] == 65
        assert spec_50["lot_size"] == 50
        assert spec_25["lot_size"] == 25

        # All are distinct — none was overwritten
        assert count_contract_specs(db) == 4


# ===================================================================
# 18. Research safety — missing lot_size pattern
# ===================================================================


class TestResearchSafety:
    """Pseudo-pattern: research must not invent a lot_size."""

    def test_missing_lot_size_pattern(self):
        db = _fresh_db()
        # No contract metadata stored
        spec = get_contract_specification(db, "NSE_FO|47983|17-04-2025")

        # Research code pattern:
        if spec is None or spec["lot_size"] is None:
            historical_lot_size = None
            status = "UNKNOWN_HISTORICAL_LOT_SIZE"
        else:
            historical_lot_size = spec["lot_size"]
            status = "ok"

        assert historical_lot_size is None
        assert status == "UNKNOWN_HISTORICAL_LOT_SIZE"

    def test_available_lot_size_pattern(self):
        db = _fresh_db()
        upsert_contract_spec(db, FIXTURE_PE_20400)
        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])

        if spec is None or spec["lot_size"] is None:
            historical_lot_size = None
            status = "UNKNOWN_HISTORICAL_LOT_SIZE"
        else:
            historical_lot_size = spec["lot_size"]
            status = "ok"

        assert historical_lot_size == 75
        assert status == "ok"

    def test_null_lot_size_pattern(self):
        db = _fresh_db()
        upsert_contract_spec(db, {**FIXTURE_PE_20400, "lot_size": None})
        spec = get_contract_specification(db, FIXTURE_PE_20400["instrument_key"])

        if spec is None or spec["lot_size"] is None:
            historical_lot_size = None
            status = "UNKNOWN_HISTORICAL_LOT_SIZE"
        else:
            historical_lot_size = spec["lot_size"]
            status = "ok"

        assert historical_lot_size is None
        assert status == "UNKNOWN_HISTORICAL_LOT_SIZE"


# ===================================================================
# Helpers
# ===================================================================


def _fresh_db():
    """Create a fresh in-memory DB session."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return TestSession()
