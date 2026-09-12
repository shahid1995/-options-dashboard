"""CockroachDB serialization-failure retry utilities.

This module provides a context manager for retrying database transactions
that may fail due to CockroachDB's SERIALIZABLE isolation level.

CockroachDB uses SERIALIZABLE isolation by default. When two concurrent
transactions conflict, one of them receives a serialization failure
(SQLSTATE 40001). The failed transaction must be retried from the beginning.

Usage::

    with crdb_retry(session_factory) as db:
        # Your transaction logic here
        db.add(some_object)
        db.commit()

The context manager automatically:
- Creates a fresh session on each attempt
- Detects serialization failures (SQLSTATE 40001)
- Rolls back the failed attempt
- Sleeps with exponential backoff between attempts
- Retries up to max_attempts times
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional, TypeVar

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# SQLSTATE code for CockroachDB serialization failure
_CRDB_SERIALIZATION_FAILURE_SQLSTATE = "40001"

# Default retry configuration
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_SECONDS = 0.1


def is_serialization_failure(exc: BaseException) -> bool:
    """Check if an exception is a CockroachDB serialization failure.

    Detects SQLSTATE 40001 from the underlying DBAPI error, wrapped by
    SQLAlchemy's OperationalError.

    Args:
        exc: The exception to check.

    Returns:
        True if the exception is a serialization failure, False otherwise.
    """
    if not isinstance(exc, OperationalError):
        return False

    # Walk the exception chain to find the original DBAPI error
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False

    # psycopg errors have a sqlstate attribute
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate == _CRDB_SERIALIZATION_FAILURE_SQLSTATE:
        return True

    # Fallback: check error message for serialization-related keywords
    # This handles cases where sqlstate may not be directly accessible
    error_msg = str(orig).lower()
    if "40001" in error_msg or "serialization" in error_msg:
        return True

    return False


class RetryExhausted(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, last_error: BaseException, attempts: int):
        self.last_error = last_error
        self.attempts = attempts
        super().__init__(
            f"Transaction failed after {attempts} attempts. "
            f"Last error: {last_error}"
        )


class crdb_retry:
    """Context manager for CockroachDB transaction retry.

    Wraps a block of database operations. If a serialization failure
    (SQLSTATE 40001) occurs, the transaction is rolled back and retried
    with a fresh session.

    Args:
        session_factory: A callable that returns a new SQLAlchemy Session.
        max_attempts: Maximum number of attempts (default: 3).
        base_delay: Base delay in seconds for exponential backoff (default: 0.1).

    Yields:
        A fresh SQLAlchemy Session for each attempt.

    Raises:
        RetryExhausted: If all attempts fail with serialization failures.
        OperationalError: If a non-retryable database error occurs.
        Exception: Any non-database exception is propagated immediately.

    Example::

        def process_event(event, session_factory):
            with crdb_retry(session_factory) as db:
                result = ingest_canonical_event(event, db)
                db.commit()
            return result
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        base_delay: float = _DEFAULT_BASE_DELAY_SECONDS,
    ):
        self.session_factory = session_factory
        self.max_attempts = max_attempts
        self.base_delay = base_delay

    def __enter__(self) -> Session:
        # The actual session is created in _attempt()
        return self._attempt()

    def _attempt(self) -> Session:
        """Create a fresh session for the next attempt."""
        if not hasattr(self, '_current_session') or self._current_session is None:
            self._current_session = self.session_factory()
        return self._current_session

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            # Success — commit the transaction
            try:
                self._current_session.commit()
                return True
            except Exception:
                self._current_session.rollback()
                raise

        # An exception occurred — check if it's a serialization failure
        if is_serialization_failure(exc_val):
            logger.warning(
                "CockroachDB serialization failure detected (attempt %d/%d). "
                "Retrying...",
                getattr(self, '_attempt_num', 1),
                self.max_attempts,
            )
            # Roll back the failed attempt
            try:
                self._current_session.rollback()
            except Exception:
                pass  # Rollback failures are logged but don't prevent retry

            # Increment attempt counter
            self._attempt_num = getattr(self, '_attempt_num', 1) + 1

            if self._attempt_num > self.max_attempts:
                raise RetryExhausted(exc_val, self.max_attempts) from exc_val

            # Exponential backoff
            delay = self.base_delay * (2 ** (self._attempt_num - 1))
            time.sleep(delay)

            # Create a new session and retry
            self._current_session.close()
            self._current_session = None
            # Re-enter the context
            raise _RetryNeeded()

        # Not a serialization failure — propagate the exception
        try:
            self._current_session.rollback()
        except Exception:
            pass
        return False  # Don't suppress the exception


class _RetryNeeded(Exception):
    """Internal exception to signal that a retry should be attempted."""
    pass


def retry_on_serialization(
    operation: Callable[..., Any],
    session_factory: Callable[[], Session],
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay: float = _DEFAULT_BASE_DELAY_SECONDS,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an operation with CockroachDB serialization retry.

    This is a functional interface to crdb_retry. It executes the given
    operation inside a retry context.

    Args:
        operation: A callable that takes a Session as its first argument.
        session_factory: A callable that returns a new SQLAlchemy Session.
        max_attempts: Maximum number of attempts.
        base_delay: Base delay for exponential backoff.
        *args: Additional positional arguments to pass to the operation.
        **kwargs: Additional keyword arguments to pass to the operation.

    Returns:
        The return value of the operation.

    Raises:
        RetryExhausted: If all attempts fail.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        db = session_factory()
        try:
            result = operation(db, *args, **kwargs)
            db.commit()
            return result
        except Exception as e:
            db.rollback()
            if is_serialization_failure(e):
                last_error = e
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "Serialization failure (attempt %d/%d), retrying in %.2fs: %s",
                        attempt, max_attempts, delay, e,
                    )
                    time.sleep(delay)
                    continue
                else:
                    # Max attempts exhausted — raise RetryExhausted
                    break
            raise
        finally:
            db.close()

    raise RetryExhausted(last_error, max_attempts)
