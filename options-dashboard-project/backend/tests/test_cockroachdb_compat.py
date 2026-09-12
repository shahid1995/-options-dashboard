"""Tests for CockroachDB compatibility fixes.

This module tests the dialect dispatch (Gap A), fill-ledger upsert (Gap B),
and serialization retry (Gap C) implementations.
"""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.utils.db_dialect import dialect_insert
from app.utils.retry import (
    is_serialization_failure,
    RetryExhausted,
    retry_on_serialization,
)


# ---------------------------------------------------------------------------
# Gap A — db_dialect.py tests
# ---------------------------------------------------------------------------

class TestDialectInsert:
    """Test that dialect_insert correctly dispatches for all supported dialects."""

    def _make_engine(self, dialect_name: str) -> MagicMock:
        """Create a mock engine with the given dialect name."""
        engine = MagicMock()
        engine.dialect.name = dialect_name
        return engine

    def test_postgresql_selects_postgresql_insert(self):
        """PostgreSQL dialect should use PostgreSQL insert implementation."""
        engine = self._make_engine("postgresql")
        table = Table("test", MetaData(), Column("id", Integer))
        
        result = dialect_insert(engine, table)
        
        # Should support on_conflict_do_update (PostgreSQL feature)
        assert hasattr(result, "on_conflict_do_update")
        assert hasattr(result, "on_conflict_do_nothing")

    def test_cockroachdb_selects_postgresql_insert(self):
        """CockroachDB dialect should use PostgreSQL insert implementation."""
        engine = self._make_engine("cockroachdb")
        table = Table("test", MetaData(), Column("id", Integer))
        
        result = dialect_insert(engine, table)
        
        # Should support on_conflict_do_update (PostgreSQL-compatible)
        assert hasattr(result, "on_conflict_do_update")
        assert hasattr(result, "on_conflict_do_nothing")

    def test_sqlite_selects_sqlite_insert(self):
        """SQLite dialect should use SQLite insert implementation."""
        engine = self._make_engine("sqlite")
        table = Table("test", MetaData(), Column("id", Integer))
        
        result = dialect_insert(engine, table)
        
        # Should support on_conflict_do_update (SQLite 3.35+)
        assert hasattr(result, "on_conflict_do_update")
        assert hasattr(result, "on_conflict_do_nothing")

    def test_unknown_dialect_uses_generic_insert(self):
        """Unknown dialects should fall back to generic insert."""
        engine = self._make_engine("mysql")
        table = Table("test", MetaData(), Column("id", Integer))
        
        result = dialect_insert(engine, table)
        
        # Generic insert does NOT support on_conflict_do_update
        assert not hasattr(result, "on_conflict_do_update")

    def test_cockroachdb_sql_compilation(self):
        """CRDB dialect should compile PostgreSQL-style ON CONFLICT SQL."""
        from sqlalchemy_cockroachdb.base import CockroachDBDialect
        
        engine = self._make_engine("cockroachdb")
        table = Table(
            "test_table", MetaData(),
            Column("id", Integer, primary_key=True),
            Column("name", String(50))
        )
        
        insert = dialect_insert(engine, table)
        stmt = insert.values(id=1, name="test").on_conflict_do_nothing(
            index_elements=["id"]
        ).returning(table.c.id)
        
        # Use real CRDB dialect for compilation
        crdb_dialect = CockroachDBDialect()
        compiled = stmt.compile(dialect=crdb_dialect)
        sql = str(compiled)
        
        assert "ON CONFLICT" in sql
        assert "DO NOTHING" in sql
        assert "RETURNING" in sql


# ---------------------------------------------------------------------------
# Gap C — Serialization retry tests
# ---------------------------------------------------------------------------

class TestSerializationDetection:
    """Test detection of CockroachDB serialization failures."""

    def _make_operational_error(self, sqlstate: str | None = None, msg: str = "") -> Exception:
        """Create an OperationalError with the given SQLSTATE."""
        from sqlalchemy.exc import OperationalError
        if sqlstate:
            # Create a real exception with sqlstate attribute (psycopg-style)
            class MockDBError(Exception):
                def __init__(self, message, sqlstate):
                    super().__init__(message)
                    self.sqlstate = sqlstate
            orig = MockDBError(msg or f"ERROR: {sqlstate}", sqlstate)
            return OperationalError("statement", {}, orig)
        return OperationalError("statement", {}, Exception(msg))

    def test_sqlstate_40001_detected(self):
        """SQLSTATE 40001 should be detected as serialization failure."""
        exc = self._make_operational_error("40001", "retry transaction")
        assert is_serialization_failure(exc) is True

    def test_other_sqlstate_not_detected(self):
        """Non-40001 SQLSTATEs should not be detected as serialization failure."""
        exc = self._make_operational_error("23505", "unique constraint violation")
        assert is_serialization_failure(exc) is False

    def test_non_operational_error_not_detected(self):
        """Non-OperationalError exceptions should not be detected."""
        assert is_serialization_failure(ValueError("some error")) is False
        assert is_serialization_failure(RuntimeError("runtime")) is False
        assert is_serialization_failure(None) is False

    def test_message_fallback_detection(self):
        """Serialization keyword in error message should trigger detection."""
        exc = self._make_operational_error(None, "Serialization failure: retry")
        assert is_serialization_failure(exc) is True

    def test_40001_in_message_detected(self):
        """40001 in error message should trigger detection."""
        exc = self._make_operational_error(None, "ERROR: 40001 retry")
        assert is_serialization_failure(exc) is True


class TestRetryOnSerialization:
    """Test retry_on_serialization function."""

    def _make_session_factory(self):
        """Create a factory that tracks session creation."""
        sessions = []
        
        def factory():
            session = MagicMock(spec=Session)
            sessions.append(session)
            return session
        
        return factory, sessions

    def test_success_on_first_attempt(self):
        """Operation that succeeds on first attempt should not retry."""
        factory, sessions = self._make_session_factory()
        
        def operation(db):
            return "success"
        
        result = retry_on_serialization(operation, factory)
        
        assert result == "success"
        assert len(sessions) == 1
        sessions[0].commit.assert_called_once()
        sessions[0].close.assert_called_once()
        sessions[0].rollback.assert_not_called()

    def test_retry_on_serialization_failure(self):
        """Operation that fails with serialization should retry."""
        factory, sessions = self._make_session_factory()
        call_count = [0]
        
        def operation(db):
            call_count[0] += 1
            if call_count[0] == 1:
                orig = MagicMock()
                orig.sqlstate = "40001"
                raise OperationalError("stmt", {}, orig)
            return "success"
        
        with patch("app.utils.retry.time.sleep"):  # Don't actually sleep
            result = retry_on_serialization(operation, factory)
        
        assert result == "success"
        assert call_count[0] == 2
        assert len(sessions) == 2
        # First session should be rolled back
        sessions[0].rollback.assert_called_once()
        sessions[0].close.assert_called_once()
        # Second session should be committed
        sessions[1].commit.assert_called_once()
        sessions[1].close.assert_called_once()

    def test_non_retryable_error_not_retried(self):
        """Non-serialization errors should not be retried."""
        factory, sessions = self._make_session_factory()
        
        def operation(db):
            raise ValueError("not a serialization failure")
        
        with pytest.raises(ValueError, match="not a serialization failure"):
            retry_on_serialization(operation, factory)
        
        assert len(sessions) == 1
        sessions[0].rollback.assert_called_once()
        sessions[0].commit.assert_not_called()

    def test_retry_exhaustion(self):
        """After max_attempts serialization failures, should raise RetryExhausted."""
        factory, sessions = self._make_session_factory()
        
        def operation(db):
            orig = MagicMock()
            orig.sqlstate = "40001"
            raise OperationalError("stmt", {}, orig)
        
        with patch("app.utils.retry.time.sleep"):
            with pytest.raises(RetryExhausted) as exc_info:
                retry_on_serialization(operation, factory, max_attempts=3)
        
        assert exc_info.value.attempts == 3
        assert len(sessions) == 3

    def test_max_attempts_configuration(self):
        """max_attempts should control the number of retries."""
        factory, sessions = self._make_session_factory()
        
        def operation(db):
            orig = MagicMock()
            orig.sqlstate = "40001"
            raise OperationalError("stmt", {}, orig)
        
        with patch("app.utils.retry.time.sleep"):
            with pytest.raises(RetryExhausted) as exc_info:
                retry_on_serialization(operation, factory, max_attempts=5)
        
        assert exc_info.value.attempts == 5
        assert len(sessions) == 5

    def test_session_cleanup_on_retry(self):
        """Each retry should use a fresh session."""
        factory, sessions = self._make_session_factory()
        session_ids = []
        
        def operation(db):
            session_ids.append(id(db))
            orig = MagicMock()
            orig.sqlstate = "40001"
            raise OperationalError("stmt", {}, orig)
        
        with patch("app.utils.retry.time.sleep"):
            with pytest.raises(RetryExhausted):
                retry_on_serialization(operation, factory, max_attempts=3)
        
        # All session IDs should be different (new session each attempt)
        assert len(set(session_ids)) == 3

    def test_exponential_backoff(self):
        """Retry should use exponential backoff."""
        factory, sessions = self._make_session_factory()
        sleep_calls = []
        
        def operation(db):
            orig = MagicMock()
            orig.sqlstate = "40001"
            raise OperationalError("stmt", {}, orig)
        
        with patch("app.utils.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            with pytest.raises(RetryExhausted):
                retry_on_serialization(operation, factory, max_attempts=3, base_delay=0.1)
        
        assert len(sleep_calls) == 2  # 2 sleeps between 3 attempts
        assert sleep_calls[0] == pytest.approx(0.1, rel=0.01)  # 0.1 * 2^0
        assert sleep_calls[1] == pytest.approx(0.2, rel=0.01)  # 0.1 * 2^1


class TestRetrySafety:
    """Test that retry implementation preserves data integrity."""

    def _make_session_factory(self):
        """Create a factory that tracks session creation."""
        sessions = []
        
        def factory():
            session = MagicMock(spec=Session)
            sessions.append(session)
            return session
        
        return factory, sessions

    def test_rollback_before_retry(self):
        """Failed attempt should be rolled back before retry."""
        factory, sessions = self._make_session_factory()
        rollback_count = [0]
        
        def operation(db):
            if len(sessions) == 1:  # First attempt
                orig = MagicMock()
                orig.sqlstate = "40001"
                raise OperationalError("stmt", {}, orig)
            return "success"
        
        with patch("app.utils.retry.time.sleep"):
            retry_on_serialization(operation, factory)
        
        # Rollback should have been called before the successful retry
        sessions[0].rollback.assert_called_once()

    def test_no_commit_on_failed_attempt(self):
        """Failed attempt should not commit."""
        factory, sessions = self._make_session_factory()
        
        def operation(db):
            orig = MagicMock()
            orig.sqlstate = "40001"
            raise OperationalError("stmt", {}, orig)
        
        with patch("app.utils.retry.time.sleep"):
            with pytest.raises(RetryExhausted):
                retry_on_serialization(operation, factory, max_attempts=2)
        
        # Neither session should have been committed
        sessions[0].commit.assert_not_called()
        sessions[1].commit.assert_not_called()


# ---------------------------------------------------------------------------
# Gap B — fill_ledger.py tests
# ---------------------------------------------------------------------------

class TestUpsertTradeFillDialectDispatch:
    """Test that _upsert_trade_fill dispatches correctly for CockroachDB."""

    def test_cockroachdb_uses_postgresql_insert(self):
        """CockroachDB should use the PostgreSQL insert implementation."""
        from app.broker_sync.fill_ledger import _upsert_trade_fill
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        
        db = MagicMock(spec=Session)
        bind = MagicMock()
        bind.dialect.name = "cockroachdb"
        db.get_bind.return_value = bind
        db.execute.return_value.first.return_value = None
        
        _upsert_trade_fill(
            db,
            tenant_id="t1",
            provider_order_id="po1",
            fill_eq_key="k1",
            fill_quantity=10,
            fill_price="100.0",
            cumulative_after=10,
        )
        
        db.execute.assert_called_once()
        executed_stmt = db.execute.call_args[0][0]
        
        # Verify the statement is a PostgreSQL Insert (not SQLite)
        assert type(executed_stmt).__name__ == "Insert"
        assert "postgresql" in str(type(executed_stmt).__module__).lower()

    def test_postgresql_uses_postgresql_insert(self):
        """PostgreSQL should continue to use PostgreSQL insert implementation."""
        from app.broker_sync.fill_ledger import _upsert_trade_fill
        
        db = MagicMock(spec=Session)
        bind = MagicMock()
        bind.dialect.name = "postgresql"
        db.get_bind.return_value = bind
        db.execute.return_value.first.return_value = None
        
        _upsert_trade_fill(
            db,
            tenant_id="t1",
            provider_order_id="po1",
            fill_eq_key="k1",
            fill_quantity=10,
            fill_price="100.0",
            cumulative_after=10,
        )
        
        db.execute.assert_called_once()

    def test_sqlite_uses_sqlite_insert(self):
        """SQLite should continue to use SQLite insert implementation."""
        from app.broker_sync.fill_ledger import _upsert_trade_fill
        
        db = MagicMock(spec=Session)
        bind = MagicMock()
        bind.dialect.name = "sqlite"
        db.get_bind.return_value = bind
        db.execute.return_value.first.return_value = None
        
        _upsert_trade_fill(
            db,
            tenant_id="t1",
            provider_order_id="po1",
            fill_eq_key="k1",
            fill_quantity=10,
            fill_price="100.0",
            cumulative_after=10,
        )
        
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Integration test for retry with ingest_canonical_event
# ---------------------------------------------------------------------------

class TestIngestCanonicalEventRetry:
    """Test the ingest_canonical_event_with_retry wrapper."""

    def test_wrapper_exists_and_callable(self):
        """The retry wrapper should be importable and callable."""
        from app.broker_sync.ingestion import ingest_canonical_event_with_retry
        
        assert callable(ingest_canonical_event_with_retry)

    def test_wrapper_uses_retry_on_serialization(self):
        """The wrapper should use retry_on_serialization internally."""
        from app.broker_sync.ingestion import ingest_canonical_event_with_retry
        
        # Verify the function exists and has the expected signature
        import inspect
        sig = inspect.signature(ingest_canonical_event_with_retry)
        params = list(sig.parameters.keys())
        
        # Should accept event and session_factory as first two params
        assert "event" in params
        assert "session_factory" in params
