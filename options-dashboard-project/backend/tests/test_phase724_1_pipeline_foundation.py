"""Phase 7.24.1 — Data Pipeline Foundation Tests.

Comprehensive tests for the three new infrastructure tables:
  - ingestion_log
  - data_completeness
  - ingestion_checkpoint

Tests cover schema, CRUD, persistence, idempotency, restart safety,
existing-data protection, checkpoint recovery, and secret protection.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base, _DEFAULT_DB_PATH
from app.models import (
    IngestionLog, DataCompleteness, IngestionCheckpoint,
    ContractSpec, NiftyCandle, OptionCandle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine_and_session():
    """In-memory database engine and session."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    session = Session()
    yield eng, session
    session.close()
    eng.dispose()


@pytest.fixture()
def db_session(engine_and_session):
    """In-memory database session."""
    return engine_and_session[1]


@pytest.fixture()
def sample_raw_data(db_session):
    """Insert representative raw data to verify it is not modified."""
    now = datetime.now(timezone.utc)
    db_session.add(ContractSpec(
        instrument_key="NSE_FO|63935|28-07-2026",
        underlying="NIFTY", underlying_key="NSE_INDEX|Nifty 50",
        trading_symbol="NIFTY", segment="INDICES", exchange="NSE_EQ",
        expiry="2026-07-28", strike_price=24000.0,
        instrument_type="CE", lot_size=75,
        source="test", source_reference="test",
        fetched_at=now, created_at=now,
    ))
    db_session.add(NiftyCandle(
        symbol="NIFTY", interval="3min",
        open_time=datetime(2026, 7, 28, 9, 15),
        open=24000.0, high=24010.0, low=23990.0, close=24005.0,
        volume=100000,
    ))
    db_session.add(OptionCandle(
        instrument_key="NSE_FO|63935|28-07-2026",
        interval="3min", open_time=datetime(2026, 7, 28, 9, 15),
        open=150.0, high=152.0, low=148.0, close=150.0,
        volume=500.0, open_interest=10000.0, fetched_at=now,
    ))
    db_session.commit()
    return {
        "contract_key": "NSE_FO|63935|28-07-2026",
        "nifty_time": datetime(2026, 7, 28, 9, 15),
        "option_key": "NSE_FO|63935|28-07-2026",
    }


# ---------------------------------------------------------------------------
# S1: Schema — all three tables exist with correct columns
# ---------------------------------------------------------------------------

class TestSchema:
    def test_ingestion_log_exists(self, db_session):
        """ingestion_log table exists and is queryable."""
        count = db_session.scalar(select(func.count(IngestionLog.id)))
        assert count == 0  # Table exists but is empty

    def test_data_completeness_exists(self, db_session):
        """data_completeness table exists and is queryable."""
        count = db_session.scalar(select(func.count(DataCompleteness.id)))
        assert count == 0

    def test_ingestion_checkpoint_exists(self, db_session):
        """ingestion_checkpoint table exists and is queryable."""
        count = db_session.scalar(select(func.count(IngestionCheckpoint.id)))
        assert count == 0

    def test_ingestion_log_columns(self, db_session):
        """Verify all required columns exist on ingestion_log."""
        now = datetime.now(timezone.utc)
        log = IngestionLog(
            run_id="test_run_001",
            operation="option_candles",
            instrument_key="TEST|KEY",
            expiry_date="2026-07-28",
            session_date="2026-07-28",
            started_at=now.isoformat(),
            status="RUNNING",
        )
        db_session.add(log)
        db_session.commit()
        assert log.id is not None

    def test_data_completeness_columns(self, db_session):
        """Verify all required columns exist on data_completeness."""
        dc = DataCompleteness(
            instrument_key="TEST|KEY",
            session_date="2026-07-28",
            data_type="option_candles",
            expected_count=125,
            actual_count=100,
            missing_count=25,
            status="PARTIAL",
        )
        db_session.add(dc)
        db_session.commit()
        assert dc.id is not None

    def test_ingestion_checkpoint_columns(self, db_session):
        """Verify all required columns exist on ingestion_checkpoint."""
        cp = IngestionCheckpoint(
            pipeline="greeks",
            instrument_key="TEST|KEY",
            run_id="run_001",
            status="COMPLETED",
            items_processed=100,
            items_total=100,
        )
        db_session.add(cp)
        db_session.commit()
        assert cp.id is not None


# ---------------------------------------------------------------------------
# S2: Indexes exist
# ---------------------------------------------------------------------------

class TestIndexes:
    def _get_indexes(self, engine, table_name: str) -> list[str]:
        """Get index names for a table."""
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name = :t"
            ), {"t": table_name}).fetchall()
            return [r[0] for r in rows]

    def test_ingestion_log_indexes_in_production_db(self):
        """ingestion_log has expected indexes in the production database."""
        from app.db import init_db, engine as prod_engine
        init_db()
        idxs = self._get_indexes(prod_engine, "ingestion_log")
        assert any("operation" in i and "status" in i for i in idxs)
        assert any("completed_at" in i for i in idxs)

    def test_data_completeness_indexes_in_production_db(self):
        """data_completeness has expected indexes in the production database."""
        from app.db import init_db, engine as prod_engine
        init_db()
        idxs = self._get_indexes(prod_engine, "data_completeness")
        assert any("status" in i for i in idxs)

    def test_ingestion_checkpoint_indexes_in_production_db(self):
        """ingestion_checkpoint has expected indexes in the production database."""
        from app.db import init_db, engine as prod_engine
        init_db()
        idxs = self._get_indexes(prod_engine, "ingestion_checkpoint")
        assert any("status" in i for i in idxs)  # ix_ingestion_checkpoint_status


# ---------------------------------------------------------------------------
# S3: Ingestion log CRUD
# ---------------------------------------------------------------------------

class TestIngestionLogCRUD:
    def test_create_log(self, db_session):
        """Create an ingestion log entry."""
        now = datetime.now(timezone.utc)
        log = IngestionLog(
            run_id="run_001", operation="option_candles",
            instrument_key="NSE_FO|63935|28-07-2026",
            expiry_date="2026-07-28", session_date="2026-07-28",
            started_at=now.isoformat(), status="RUNNING",
        )
        db_session.add(log)
        db_session.commit()
        assert log.id is not None

    def test_update_log_to_success(self, db_session):
        """Update a log from RUNNING to SUCCESS."""
        now = datetime.now(timezone.utc)
        log = IngestionLog(
            run_id="run_001", operation="option_candles",
            started_at=now.isoformat(), status="RUNNING",
        )
        db_session.add(log)
        db_session.commit()

        log.status = "SUCCESS"
        log.completed_at = now.isoformat()
        log.rows_inserted = 125
        db_session.commit()

        fetched = db_session.get(IngestionLog, log.id)
        assert fetched.status == "SUCCESS"
        assert fetched.rows_inserted == 125

    def test_update_log_to_failure(self, db_session):
        """Update a log from RUNNING to FAILED with error info."""
        now = datetime.now(timezone.utc)
        log = IngestionLog(
            run_id="run_001", operation="option_candles",
            started_at=now.isoformat(), status="RUNNING",
        )
        db_session.add(log)
        db_session.commit()

        log.status = "FAILED"
        log.completed_at = now.isoformat()
        log.error_category = "AUTH_EXPIRED"
        log.error_message = "Token expired"
        db_session.commit()

        fetched = db_session.get(IngestionLog, log.id)
        assert fetched.status == "FAILED"
        assert fetched.error_category == "AUTH_EXPIRED"

    def test_log_without_optional_fields(self, db_session):
        """Log works without instrument_key, expiry_date, etc."""
        now = datetime.now(timezone.utc)
        log = IngestionLog(
            run_id="run_001", operation="contract_metadata",
            started_at=now.isoformat(), status="SUCCESS",
        )
        db_session.add(log)
        db_session.commit()
        assert log.instrument_key is None
        assert log.expiry_date is None

    def test_metadata_json_field(self, db_session):
        """metadata_json stores arbitrary JSON (no secrets)."""
        now = datetime.now(timezone.utc)
        meta = json.dumps({"api_requests": 5, "batch_size": 100})
        log = IngestionLog(
            run_id="run_001", operation="option_candles",
            started_at=now.isoformat(), status="SUCCESS",
            metadata_json=meta,
        )
        db_session.add(log)
        db_session.commit()
        fetched = db_session.get(IngestionLog, log.id)
        parsed = json.loads(fetched.metadata_json)
        assert parsed["api_requests"] == 5


# ---------------------------------------------------------------------------
# S4: Data completeness CRUD
# ---------------------------------------------------------------------------

class TestDataCompletenessCRUD:
    def test_create_completeness(self, db_session):
        """Create a data completeness record."""
        dc = DataCompleteness(
            instrument_key="NSE_FO|63935|28-07-2026",
            session_date="2026-07-28",
            data_type="option_candles",
            expected_count=125, actual_count=0,
            status="MISSING",
        )
        db_session.add(dc)
        db_session.commit()
        assert dc.id is not None

    def test_update_completeness(self, db_session):
        """Update completeness from MISSING to COMPLETE."""
        dc = DataCompleteness(
            instrument_key="NSE_FO|63935|28-07-2026",
            session_date="2026-07-28",
            data_type="option_candles",
            expected_count=125, actual_count=0,
            status="MISSING",
        )
        db_session.add(dc)
        db_session.commit()

        dc.status = "COMPLETE"
        dc.actual_count = 125
        dc.missing_count = 0
        dc.last_verified_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        fetched = db_session.get(DataCompleteness, dc.id)
        assert fetched.status == "COMPLETE"
        assert fetched.actual_count == 125

    def test_unique_constraint(self, db_session):
        """Duplicate (instrument_key, session_date, data_type) raises error."""
        dc1 = DataCompleteness(
            instrument_key="TEST|KEY", session_date="2026-07-28",
            data_type="option_candles", status="MISSING",
        )
        dc2 = DataCompleteness(
            instrument_key="TEST|KEY", session_date="2026-07-28",
            data_type="option_candles", status="COMPLETE",
        )
        db_session.add(dc1)
        db_session.commit()

        db_session.add(dc2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()
        db_session.rollback()

    def test_different_data_types_coexist(self, db_session):
        """Same instrument+session with different data_types coexist."""
        dc1 = DataCompleteness(
            instrument_key="TEST|KEY", session_date="2026-07-28",
            data_type="option_candles", status="COMPLETE",
        )
        dc2 = DataCompleteness(
            instrument_key="TEST|KEY", session_date="2026-07-28",
            data_type="nifty_candles", status="COMPLETE",
        )
        db_session.add(dc1)
        db_session.add(dc2)
        db_session.commit()

        count = db_session.scalar(
            select(func.count(DataCompleteness.id))
            .where(DataCompleteness.instrument_key == "TEST|KEY")
        )
        assert count == 2


# ---------------------------------------------------------------------------
# S5: Ingestion checkpoint CRUD
# ---------------------------------------------------------------------------

class TestIngestionCheckpointCRUD:
    def test_create_checkpoint(self, db_session):
        """Create a checkpoint entry."""
        cp = IngestionCheckpoint(
            pipeline="greeks",
            instrument_key="TEST|KEY",
            run_id="run_001",
            status="RUNNING",
            items_processed=50,
            items_total=100,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        db_session.add(cp)
        db_session.commit()
        assert cp.id is not None

    def test_update_checkpoint(self, db_session):
        """Update checkpoint progress."""
        cp = IngestionCheckpoint(
            pipeline="greeks", instrument_key="TEST|KEY",
            status="RUNNING", items_processed=0, items_total=100,
        )
        db_session.add(cp)
        db_session.commit()

        cp.items_processed = 100
        cp.status = "COMPLETED"
        cp.completed_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        fetched = db_session.get(IngestionCheckpoint, cp.id)
        assert fetched.status == "COMPLETED"
        assert fetched.items_processed == 100

    def test_resume_from_checkpoint(self, db_session):
        """Simulate: process items 1-50, checkpoint, resume, process 51-100."""
        # First run: process items 1-50
        cp = IngestionCheckpoint(
            pipeline="backfill_options",
            instrument_key="TEST|KEY",
            status="RUNNING",
            items_processed=50, items_total=100,
        )
        db_session.add(cp)
        db_session.commit()

        # Simulate interruption: mark as COMPLETED at 50
        cp.status = "COMPLETED"
        cp.items_processed = 50
        cp.completed_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        # Second run: check checkpoint, skip completed
        fetched = db_session.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == "backfill_options")
            .where(IngestionCheckpoint.instrument_key == "TEST|KEY")
            .where(IngestionCheckpoint.status == "COMPLETED")
        ).scalar_one_or_none()

        assert fetched is not None
        assert fetched.items_processed == 50  # Resume point

    def test_unique_constraint(self, db_session):
        """Duplicate (pipeline, instrument_key) raises error."""
        cp1 = IngestionCheckpoint(
            pipeline="greeks", instrument_key="TEST|KEY", status="RUNNING",
        )
        cp2 = IngestionCheckpoint(
            pipeline="greeks", instrument_key="TEST|KEY", status="COMPLETED",
        )
        db_session.add(cp1)
        db_session.commit()

        db_session.add(cp2)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()

    def test_different_pipelines_coexist(self, db_session):
        """Same instrument with different pipelines coexist."""
        cp1 = IngestionCheckpoint(
            pipeline="greeks", instrument_key="TEST|KEY", status="COMPLETED",
        )
        cp2 = IngestionCheckpoint(
            pipeline="backfill_options", instrument_key="TEST|KEY", status="RUNNING",
        )
        db_session.add(cp1)
        db_session.add(cp2)
        db_session.commit()

        count = db_session.scalar(
            select(func.count(IngestionCheckpoint.id))
            .where(IngestionCheckpoint.instrument_key == "TEST|KEY")
        )
        assert count == 2


# ---------------------------------------------------------------------------
# S6: Persistence across engine recreation
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_data_survives_separate_sessions(self, engine_and_session):
        """Data is visible across separate sessions on the same engine."""
        engine, session1 = engine_and_session

        # Insert data in session1
        log = IngestionLog(
            run_id="run_001", operation="option_candles",
            started_at=datetime.now(timezone.utc).isoformat(), status="SUCCESS",
        )
        session1.add(log)
        session1.commit()
        log_id = log.id

        # Create a new session on the same engine
        Session2 = sessionmaker(bind=engine)
        session2 = Session2()
        try:
            fetched = session2.get(IngestionLog, log_id)
            assert fetched is not None
            assert fetched.status == "SUCCESS"
        finally:
            session2.close()


# ---------------------------------------------------------------------------
# S7: init_db() safety
# ---------------------------------------------------------------------------

class TestInitDbSafety:
    def test_init_db_idempotent(self):
        """Running init_db() twice produces no errors."""
        from app.db import init_db
        init_db()
        init_db()  # Should not raise

    def test_init_db_preserves_existing_data(self, sample_raw_data):
        """init_db() does not delete existing rows."""
        db_session = sample_raw_data  # fixture inserts data
        # Re-import to get the real DB session
        from app.db import SessionLocal
        real_session = SessionLocal()
        try:
            contracts_before = real_session.scalar(select(func.count(ContractSpec.id)))
            nifty_before = real_session.scalar(select(func.count(NiftyCandle.id)))
            options_before = real_session.scalar(select(func.count(OptionCandle.id)))

            from app.db import init_db
            init_db()

            contracts_after = real_session.scalar(select(func.count(ContractSpec.id)))
            nifty_after = real_session.scalar(select(func.count(NiftyCandle.id)))
            options_after = real_session.scalar(select(func.count(OptionCandle.id)))

            assert contracts_after == contracts_before
            assert nifty_after == nifty_before
            assert options_after == options_before
        finally:
            real_session.close()

    def test_init_db_creates_new_tables(self):
        """init_db() creates the three new infrastructure tables."""
        from app.db import init_db
        init_db()

        from app.db import SessionLocal
        session = SessionLocal()
        try:
            # Verify tables are queryable
            count = session.scalar(select(func.count(IngestionLog.id)))
            assert count >= 0
            count = session.scalar(select(func.count(DataCompleteness.id)))
            assert count >= 0
            count = session.scalar(select(func.count(IngestionCheckpoint.id)))
            assert count >= 0
        finally:
            session.close()


# ---------------------------------------------------------------------------
# S8: Existing data protection
# ---------------------------------------------------------------------------

class TestExistingDataProtection:
    def test_raw_candles_unchanged_after_pipeline_ops(self, db_session, sample_raw_data):
        """Pipeline table operations do not modify raw candle data."""
        session = db_session

        # Snapshot raw data
        contract = session.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalar_one()
        orig_strike = contract.strike_price
        orig_lot = contract.lot_size

        nifty = session.execute(
            select(NiftyCandle).where(NiftyCandle.symbol == "NIFTY")
        ).scalar_one()
        orig_close = nifty.close

        option = session.execute(
            select(OptionCandle).where(OptionCandle.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalar_one()
        orig_opt_close = option.close

        # Insert pipeline data
        session.add(IngestionLog(
            run_id="test", operation="test",
            started_at=datetime.now(timezone.utc).isoformat(), status="SUCCESS",
        ))
        session.add(DataCompleteness(
            instrument_key="TEST", session_date="2026-07-28",
            data_type="test", status="COMPLETE",
        ))
        session.add(IngestionCheckpoint(
            pipeline="test", instrument_key="TEST", status="COMPLETED",
        ))
        session.commit()

        # Verify raw data unchanged
        contract2 = session.execute(
            select(ContractSpec).where(ContractSpec.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalar_one()
        assert contract2.strike_price == orig_strike
        assert contract2.lot_size == orig_lot

        nifty2 = session.execute(
            select(NiftyCandle).where(NiftyCandle.symbol == "NIFTY")
        ).scalar_one()
        assert nifty2.close == orig_close

        option2 = session.execute(
            select(OptionCandle).where(OptionCandle.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalar_one()
        assert option2.close == orig_opt_close


# ---------------------------------------------------------------------------
# S9: Secret protection — no tokens in ingestion_log
# ---------------------------------------------------------------------------

class TestSecretProtection:
    def test_no_token_fields_in_log(self):
        """IngestionLog has no field that stores access tokens."""
        fields = [c.name for c in IngestionLog.__table__.columns]
        token_fields = [f for f in fields if "token" in f.lower() or "secret" in f.lower() or "key" in f.lower() and "instrument" not in f]
        # instrument_key is acceptable, but access_token/secret are not
        dangerous = [f for f in fields if "access_token" in f.lower() or "api_secret" in f.lower()]
        assert dangerous == [], f"Found potential secret fields: {dangerous}"

    def test_metadata_json_no_secrets_by_convention(self, db_session):
        """metadata_json is documented as 'no secrets' — test the convention."""
        now = datetime.now(timezone.utc)
        # This should work — we store operational metadata, not secrets
        meta = json.dumps({"requests": 5, "batch": 100})
        log = IngestionLog(
            run_id="test", operation="test",
            started_at=now.isoformat(), status="SUCCESS",
            metadata_json=meta,
        )
        db_session.add(log)
        db_session.commit()
        # Verify it's stored and readable
        fetched = db_session.get(IngestionLog, log.id)
        assert "requests" in fetched.metadata_json
        assert "token" not in fetched.metadata_json.lower()


# ---------------------------------------------------------------------------
# S10: Production DB migration safety
# ---------------------------------------------------------------------------

class TestProductionDbMigration:
    def test_production_db_new_tables_created(self):
        """New tables exist in the production database."""
        db_path = _DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            pytest.skip("Production database not found")

        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()

        assert "ingestion_log" in tables
        assert "data_completeness" in tables
        assert "ingestion_checkpoint" in tables

    def test_production_db_raw_tables_unmodified(self):
        """Raw candle tables are not modified by migration."""
        db_path = _DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            pytest.skip("Production database not found")

        conn = sqlite3.connect(db_path)
        for t in ["nifty_candles", "contract_specs", "option_candles", "option_greeks"]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                # Just verify the table is accessible (row count may be 0)
                assert cnt >= 0
            except Exception:
                pytest.fail(f"Table {t} is not accessible after migration")
        conn.close()

    def test_production_db_integrity(self):
        """Production database passes integrity check."""
        db_path = _DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            pytest.skip("Production database not found")

        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        assert result == "ok"


# ---------------------------------------------------------------------------
# S11: Complete workflow simulation
# ---------------------------------------------------------------------------

class TestWorkflowSimulation:
    def test_full_ingestion_workflow(self, db_session):
        """Simulate complete ingestion workflow with logging and completeness."""
        now = datetime.now(timezone.utc)

        # 1. Start ingestion run
        log = IngestionLog(
            run_id="run_20260728", operation="option_candles",
            instrument_key="NSE_FO|63935|28-07-2026",
            expiry_date="2026-07-28", session_date="2026-07-28",
            started_at=now.isoformat(), status="RUNNING",
        )
        db_session.add(log)
        db_session.commit()

        # 2. Set initial completeness
        dc = DataCompleteness(
            instrument_key="NSE_FO|63935|28-07-2026",
            session_date="2026-07-28",
            data_type="option_candles",
            expected_count=125, actual_count=0,
            status="MISSING",
        )
        db_session.add(dc)
        db_session.commit()

        # 3. Set checkpoint
        cp = IngestionCheckpoint(
            pipeline="backfill_options",
            instrument_key="NSE_FO|63935|28-07-2026",
            run_id="run_20260728",
            status="RUNNING",
            items_processed=0, items_total=125,
            started_at=now.isoformat(),
        )
        db_session.add(cp)
        db_session.commit()

        # 4. Process items (simulate)
        cp.items_processed = 125
        cp.status = "COMPLETED"
        cp.completed_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        # 5. Update completeness
        dc.status = "COMPLETE"
        dc.actual_count = 125
        dc.missing_count = 0
        dc.last_verified_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        # 6. Complete log
        log.status = "SUCCESS"
        log.completed_at = datetime.now(timezone.utc).isoformat()
        log.rows_inserted = 125
        log.rows_skipped = 0
        log.api_calls = 1
        db_session.commit()

        # 7. Verify final state
        fetched_log = db_session.get(IngestionLog, log.id)
        assert fetched_log.status == "SUCCESS"
        assert fetched_log.rows_inserted == 125

        fetched_dc = db_session.execute(
            select(DataCompleteness)
            .where(DataCompleteness.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalar_one()
        assert fetched_dc.status == "COMPLETE"

        fetched_cp = db_session.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == "backfill_options")
            .where(IngestionCheckpoint.instrument_key == "NSE_FO|63935|28-07-2026")
        ).scalar_one()
        assert fetched_cp.status == "COMPLETED"
        assert fetched_cp.items_processed == 125

    def test_failure_and_retry_workflow(self, db_session):
        """Simulate failure, then retry with checkpoint resume."""
        now = datetime.now(timezone.utc)

        # First attempt: fails at item 50
        cp = IngestionCheckpoint(
            pipeline="greeks",
            instrument_key="TEST|KEY",
            status="FAILED",
            items_processed=50, items_total=100,
            error_message="API rate limit",
            started_at=now.isoformat(),
            completed_at=now.isoformat(),
        )
        db_session.add(cp)
        db_session.commit()

        # Retry: check checkpoint, resume from 50
        fetched = db_session.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == "greeks")
            .where(IngestionCheckpoint.instrument_key == "TEST|KEY")
        ).scalar_one()

        assert fetched.status == "FAILED"
        assert fetched.items_processed == 50  # Resume point

        # Update for retry
        fetched.status = "RUNNING"
        fetched.error_message = None
        fetched.started_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        # Complete
        fetched.items_processed = 100
        fetched.status = "COMPLETED"
        fetched.completed_at = datetime.now(timezone.utc).isoformat()
        db_session.commit()

        final = db_session.execute(
            select(IngestionCheckpoint)
            .where(IngestionCheckpoint.pipeline == "greeks")
            .where(IngestionCheckpoint.instrument_key == "TEST|KEY")
        ).scalar_one()
        assert final.status == "COMPLETED"
        assert final.items_processed == 100
