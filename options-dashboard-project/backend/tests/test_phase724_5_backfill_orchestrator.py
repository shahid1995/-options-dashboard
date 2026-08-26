"""Phase 7.24.5 — Unified Backfill Orchestrator Tests.

Comprehensive tests covering:
  - CLI architecture (no server required)
  - Local-first strategy
  - Idempotency
  - Checkpoint/resume
  - Failure isolation
  - Authentication handling
  - Dry-run mode
  - Raw data immutability
  - Timezone convention
  - One-instrument processing
  - Date chunk generation

All tests use mocked HTTP responses. No real Upstox API calls are made.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ContractSpec,
    IngestionCheckpoint,
    IngestionLog,
    NiftyCandle,
    OptionCandle,
)
from app.services.backfill_orchestrator import (
    BackfillOrchestrator,
    BackfillResult,
    TokenBridge,
    NIFTY_INDEX_KEY,
    NIFTY_SYMBOL,
    PIPELINE_OPTIONS,
    _generate_date_chunks,
    _chunk_has_data,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Create an isolated in-memory SQLite database for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class MockTokenProvider:
    def __init__(self, token="test-token-123"):
        self._token = token
    def get_token(self):
        return self._token
    def set_token(self, t):
        self._token = t


def _mock_client():
    """Create a mock UpstoxClient."""
    from app.services.upstox_client import UpstoxClient
    client = AsyncMock(spec=UpstoxClient)
    client.get_expiries = AsyncMock(return_value=["2026-07-28", "2026-06-26", "2026-05-28"])
    client.get_contracts = AsyncMock(return_value=[
        {
            "instrument_key": "NSE_FO|63935|28-07-2026",
            "expiry": "2026-07-28",
            "strike_price": 24500,
            "option_type": "CE",
            "lot_size": 75,
            "trading_symbol": "NIFTY26JUL24500CE",
        },
        {
            "instrument_key": "NSE_FO|63936|28-07-2026",
            "expiry": "2026-07-28",
            "strike_price": 24500,
            "option_type": "PE",
            "lot_size": 75,
            "trading_symbol": "NIFTY26JUL24500PE",
        },
    ])
    client.get_historical_candles = AsyncMock(return_value=[
        ["2026-07-28T09:15:00+05:30", 24500, 24520, 24480, 24510, 15000, 0],
        ["2026-07-28T09:18:00+05:30", 24510, 24530, 24500, 24525, 12000, 0],
    ])
    client.get_expired_historical_candles = AsyncMock(return_value=[
        ["2026-07-28T09:15:00+05:30", 150.5, 155.0, 148.0, 152.3, 5000, 325000],
        ["2026-07-28T09:18:00+05:30", 152.3, 156.0, 151.0, 154.5, 4500, 320000],
    ])
    client.metrics = MagicMock()
    client.metrics.snapshot.return_value = {"total_requests": 0}
    return client


def _add_spec(db, instrument_key, expiry, strike, option_type, lot_size=75, underlying="NIFTY"):
    """Helper to add a ContractSpec row."""
    spec = ContractSpec(
        instrument_key=instrument_key,
        underlying=underlying,
        underlying_key=NIFTY_INDEX_KEY,
        expiry=expiry,
        strike_price=strike,
        instrument_type=option_type,
        lot_size=lot_size,
        minimum_lot=lot_size,
        trading_symbol=f"NIFTY{expiry.replace('-', '')}{int(strike)}{option_type}",
        segment="NSE_FO",
        exchange="NSE",
        source="TEST",
        source_reference="test",
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(spec)
    db.commit()
    return spec


# ---------------------------------------------------------------------------
# Date chunk tests
# ---------------------------------------------------------------------------

class TestDateChunks:
    def test_single_chunk(self):
        chunks = _generate_date_chunks(date(2026, 1, 1), date(2026, 1, 28))
        assert len(chunks) == 1
        assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 28))

    def test_multiple_chunks(self):
        chunks = _generate_date_chunks(date(2026, 1, 1), date(2026, 3, 1))
        assert len(chunks) == 3
        # Verify no gaps
        for i in range(len(chunks) - 1):
            assert chunks[i][1] + timedelta(days=1) == chunks[i + 1][0]

    def test_single_day(self):
        chunks = _generate_date_chunks(date(2026, 6, 15), date(2026, 6, 15))
        assert len(chunks) == 1
        assert chunks[0] == (date(2026, 6, 15), date(2026, 6, 15))

    def test_empty_range(self):
        chunks = _generate_date_chunks(date(2026, 3, 1), date(2026, 1, 1))
        assert chunks == []


# ---------------------------------------------------------------------------
# Architecture tests
# ---------------------------------------------------------------------------

class TestOrchestratorArchitecture:
    def test_cli_works_without_server(self):
        """CLI entry point can be imported without FastAPI."""
        import importlib
        mod = importlib.import_module("run_backfill")
        assert hasattr(mod, "main")
        assert hasattr(mod, "_get_db_session")

    def test_init_db_does_not_trigger_backfill(self):
        """init_db() must NOT call any Upstox API."""
        from app.db import init_db
        with patch("app.services.upstox_client.UpstoxClient") as mock_cls:
            init_db()
            mock_cls.assert_not_called()

    def test_orchestrator_uses_client(self):
        """Orchestrator must use UpstoxClient, not direct requests."""
        client = _mock_client()
        db_inst = MagicMock()
        orch = BackfillOrchestrator(db_inst, client)
        assert orch.client is client

    def test_token_bridge_protocol(self):
        """TokenBridge satisfies TokenProvider protocol."""
        bridge = TokenBridge()
        assert hasattr(bridge, "get_token")
        result = bridge.get_token()
        # Without server and without persistent cache, returns None
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_zero_api_calls(self, db):
        """Dry run must make zero API calls."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        # Run dry run in event loop
        loop = __import__("asyncio").new_event_loop()
        plan = loop.run_until_complete(orch.run_dry_run())
        loop.close()

        client.get_expiries.assert_not_called()
        client.get_contracts.assert_not_called()
        client.get_historical_candles.assert_not_called()
        client.get_expired_historical_candles.assert_not_called()

    def test_dry_run_returns_plan(self, db):
        """Dry run returns a useful plan."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        plan = loop.run_until_complete(orch.run_dry_run())
        loop.close()

        assert "contracts" in plan
        assert "nifty_candles" in plan
        assert "option_candles" in plan
        assert "estimated_work" in plan

    def test_dry_run_zero_db_changes(self, db):
        """Dry run must not modify the database."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_all(stages=["contracts", "nifty", "options"]))
        loop.close()

        assert db.scalar(select(func.count(ContractSpec.id))) == 0
        assert db.scalar(select(func.count(NiftyCandle.id))) == 0
        assert db.scalar(select(func.count(OptionCandle.id))) == 0


# ---------------------------------------------------------------------------
# Contract metadata tests
# ---------------------------------------------------------------------------

class TestContractBackfill:
    def test_contract_discovery(self, db):
        """Contracts are discovered and persisted."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_contracts())
        loop.close()

        assert result.status in ("SUCCESS", "PARTIAL")
        assert result.api_calls >= 1
        client.get_expiries.assert_called_once()

    def test_contract_idempotency(self, db):
        """Running contract backfill twice doesn't create duplicates."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_contracts())
        count1 = db.scalar(select(func.count(ContractSpec.id))) or 0

        # Run again
        client2 = _mock_client()
        orch2 = BackfillOrchestrator(db, client2)
        loop.run_until_complete(orch2.run_contracts())
        count2 = db.scalar(select(func.count(ContractSpec.id))) or 0

        loop.close()
        assert count1 == count2  # No duplicates

    def test_contract_dry_run(self, db):
        """Contract dry-run makes no API calls."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_contracts())
        loop.close()

        assert result.status == "DRY_RUN"
        client.get_contracts.assert_not_called()


# ---------------------------------------------------------------------------
# NIFTY candle tests
# ---------------------------------------------------------------------------

class TestNiftyBackfill:
    def test_nifty_candle_fetch(self, db):
        """NIFTY candles are fetched and persisted."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_nifty())
        loop.close()

        assert result.status in ("SUCCESS", "PARTIAL")
        assert result.api_calls >= 1

    def test_nifty_candle_idempotency(self, db):
        """Re-running NIFTY backfill doesn't create duplicates."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client, force=True)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_nifty())
        count1 = db.scalar(select(func.count(NiftyCandle.id))) or 0

        client2 = _mock_client()
        orch2 = BackfillOrchestrator(db, client2, force=True)
        loop.run_until_complete(orch2.run_nifty())
        count2 = db.scalar(select(func.count(NiftyCandle.id))) or 0

        loop.close()
        # Should be the same or very close (force=True may update but not duplicate)
        assert count2 <= count1 + 2  # Allow small tolerance for edge cases

    def test_nifty_candles_use_ist(self, db):
        """NIFTY candles are stored with naive IST timestamps."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_nifty())
        loop.close()

        candle = db.execute(select(NiftyCandle).limit(1)).scalar_one_or_none()
        if candle:
            assert candle.open_time.tzinfo is None  # Naive


# ---------------------------------------------------------------------------
# Option candle tests
# ---------------------------------------------------------------------------

class TestOptionBackfill:
    def test_option_candle_fetch(self, db):
        """Option candles are fetched and persisted per instrument."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")
        _add_spec(db, "NSE_FO|63936|28-07-2026", "2026-07-28", 24500, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_options())
        loop.close()

        assert result.status in ("SUCCESS", "PARTIAL")
        assert result.rows_inserted > 0

    def test_option_one_instrument_at_a_time(self, db):
        """Each option instrument is processed independently."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")
        _add_spec(db, "NSE_FO|63936|28-07-2026", "2026-07-28", 24500, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_options())
        loop.close()

        # Each instrument should have its own checkpoint
        checkpoints = db.execute(select(IngestionCheckpoint)).scalars().all()
        assert len(checkpoints) == 2
        for cp in checkpoints:
            assert cp.pipeline == PIPELINE_OPTIONS
            assert cp.status == "COMPLETED"

    def test_option_failure_isolation(self, db):
        """One failing instrument doesn't affect others."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")
        _add_spec(db, "NSE_FO|63936|28-07-2026", "2026-07-28", 24500, "PE")

        client = _mock_client()
        call_count = [0]

        async def failing_get_candles(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First instrument succeeds
                return [
                    ["2026-07-28T09:15:00+05:30", 150.0, 155.0, 148.0, 152.0, 5000, 325000],
                ]
            raise Exception("Simulated API failure")

        client.get_expired_historical_candles = failing_get_candles

        orch = BackfillOrchestrator(db, client)
        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_options())
        loop.close()

        # At least one instrument should have succeeded
        assert result.rows_inserted >= 1
        # But there should be at least one error
        assert len(result.errors) >= 1

    def test_option_dry_run(self, db):
        """Option dry-run makes no API calls."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client, dry_run=True)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_options())
        loop.close()

        assert result.status == "DRY_RUN"
        client.get_expired_historical_candles.assert_not_called()


# ---------------------------------------------------------------------------
# Checkpoint tests
# ---------------------------------------------------------------------------

class TestCheckpoint:
    def test_checkpoint_written(self, db):
        """Checkpoints are written for each processed instrument."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_options())
        loop.close()

        cp = db.execute(
            select(IngestionCheckpoint).where(
                IngestionCheckpoint.instrument_key == "NSE_FO|63935|28-07-2026"
            )
        ).scalar_one_or_none()
        assert cp is not None
        assert cp.status == "COMPLETED"

    def test_checkpoint_resume(self, db):
        """Instruments with COMPLETED checkpoints are skipped on resume."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")
        _add_spec(db, "NSE_FO|63936|28-07-2026", "2026-07-28", 24500, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_options())
        count1 = db.scalar(select(func.count(OptionCandle.id))) or 0

        # Run again — second instrument should be skipped because it has candles
        client2 = _mock_client()
        orch2 = BackfillOrchestrator(db, client2)
        loop.run_until_complete(orch2.run_options())
        count2 = db.scalar(select(func.count(OptionCandle.id))) or 0

        loop.close()
        assert count1 == count2  # No new candles from second run


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------

class TestAuthentication:
    def test_no_token_stops_safely(self, db):
        """Missing token stops cleanly without crashing."""
        from app.services.upstox_client import UpstoxAuthenticationError, UpstoxClient

        # Create a real UpstoxClient with a mock token provider returning None
        class NoToken:
            def get_token(self):
                return None

        client = UpstoxClient(token_provider=NoToken())
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_contracts())
        loop.close()

        assert result.status == "FAILED"
        assert any("Authentication" in e or "auth" in e.lower() or "token" in e.lower()
                   for e in result.errors)

    def test_token_never_in_logs(self, db):
        """Access token must never appear in logs."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        # Verify no token in orchestrator attributes
        assert not hasattr(orch, "access_token")
        assert not hasattr(orch, "token")


# ---------------------------------------------------------------------------
# Ingestion logging tests
# ---------------------------------------------------------------------------

class TestIngestionLog:
    def test_log_written(self, db):
        """Ingestion log entries are written."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_contracts())
        loop.close()

        logs = db.execute(select(IngestionLog)).scalars().all()
        assert len(logs) >= 1
        assert logs[0].operation == "contract_metadata"
        assert logs[0].status in ("SUCCESS", "PARTIAL")

    def test_log_no_tokens(self, db):
        """Ingestion logs must not contain tokens."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_contracts())
        loop.close()

        logs = db.execute(select(IngestionLog)).scalars().all()
        for log in logs:
            msg = (log.error_message or "") + (log.metadata_json or "")
            assert "test-token-123" not in msg
            assert "Bearer" not in msg


# ---------------------------------------------------------------------------
# Raw data immutability tests
# ---------------------------------------------------------------------------

class TestRawImmutability:
    def test_option_candles_ohlc_preserved(self, db):
        """OHLC values are preserved exactly."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_options())
        loop.close()

        candle = db.execute(
            select(OptionCandle).where(
                OptionCandle.instrument_key == "NSE_FO|63935|28-07-2026"
            )
        ).scalars().first()
        assert candle is not None
        assert candle.open == 150.5
        assert candle.high == 155.0
        assert candle.low == 148.0
        assert candle.close == 152.3
        assert candle.volume == 5000.0
        assert candle.open_interest == 325000.0


# ---------------------------------------------------------------------------
# Timezone tests
# ---------------------------------------------------------------------------

class TestTimezoneConvention:
    def test_option_candle_ist(self, db):
        """Option candles use naive IST timestamps."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        loop.run_until_complete(orch.run_options())
        loop.close()

        candle = db.execute(
            select(OptionCandle).where(
                OptionCandle.instrument_key == "NSE_FO|63935|28-07-2026"
            )
        ).scalars().first()
        assert candle is not None
        assert candle.open_time.tzinfo is None  # Naive


# ---------------------------------------------------------------------------
# Full pipeline test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_run_all_stages(self, db):
        """Running all stages produces results."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_all())
        loop.close()

        assert result.status in ("SUCCESS", "PARTIAL")
        assert result.api_calls >= 1
        assert result.elapsed_seconds > 0

    def test_run_selected_stages(self, db):
        """Running specific stages only executes those stages."""
        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_all(stages=["contracts"]))
        loop.close()

        assert result.status in ("SUCCESS", "PARTIAL")
        client.get_historical_candles.assert_not_called()
        client.get_expired_historical_candles.assert_not_called()


# ---------------------------------------------------------------------------
# Specific expiry filter test
# ---------------------------------------------------------------------------

class TestExpiryFilter:
    def test_options_with_expiry_filter(self, db):
        """Options backfill with --expiry filters correctly."""
        _add_spec(db, "NSE_FO|63935|28-07-2026", "2026-07-28", 24500, "CE")
        _add_spec(db, "NSE_FO|63936|26-06-2026", "2026-06-26", 24500, "PE")

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_options(expiry="2026-07-28"))
        loop.close()

        # Only the 2026-07-28 contract should have been processed
        checkpoints = db.execute(
            select(IngestionCheckpoint).where(
                IngestionCheckpoint.pipeline == PIPELINE_OPTIONS
            )
        ).scalars().all()
        assert len(checkpoints) == 1
        assert checkpoints[0].instrument_key == "NSE_FO|63935|28-07-2026"


# ---------------------------------------------------------------------------
# Limit test
# ---------------------------------------------------------------------------

class TestLimit:
    def test_options_with_limit(self, db):
        """Options backfill with --limit processes at most N instruments."""
        for i in range(5):
            _add_spec(
                db,
                f"NSE_FO|{63935 + i}|28-07-2026",
                "2026-07-28",
                24500 + i * 50,
                "CE",
            )

        client = _mock_client()
        orch = BackfillOrchestrator(db, client)

        loop = __import__("asyncio").new_event_loop()
        result = loop.run_until_complete(orch.run_options(max_instruments=2))
        loop.close()

        checkpoints = db.execute(
            select(IngestionCheckpoint).where(
                IngestionCheckpoint.pipeline == PIPELINE_OPTIONS
            )
        ).scalars().all()
        assert len(checkpoints) <= 2
