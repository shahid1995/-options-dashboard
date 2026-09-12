"""CockroachDB serialization-failure retry utilities.

This module provides a helper for retrying database operations
that may fail due to CockroachDB's SERIALIZABLE isolation level.

CockroachDB uses SERIALIZABLE isolation by default. When two concurrent
transactions conflict, one of them receives a serialization failure
(SQLSTATE 40001). The failed transaction must be retried from the beginning.

Usage::

    result = retry_on_serialization(
        lambda db: ingest_canonical_event(event, db),
        session_factory=lambda: SessionLocal(),
        max_attempts=3,
        base_delay=0.1,
    )

IMPORTANT: The operation passed to retry_on_serialization must be a top-level
transaction. It should not be called within an existing transaction that
contains other atomic work, because retry_on_serialization creates its own
session and commits independently.

For operations that must participate in a caller-owned transaction, the
retry boundary must encompass the entire transaction, not just this operation.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

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

    # Access the original DBAPI error
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


def retry_on_serialization(
    operation: Callable[..., Any],
    session_factory: Callable[[], Session],
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay: float = _DEFAULT_BASE_DELAY_SECONDS,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an operation with CockroachDB serialization retry.

    This is a functional interface that executes the given operation inside
    a retry loop. Each attempt uses a fresh session from session_factory.

    IMPORTANT: The operation must be a complete, self-contained transaction.
    Do not call this within an existing transaction that contains other
    atomic work, because:

    1. Each attempt creates a NEW session
    2. The operation is committed independently after success
    3. Caller-owned work in a different session will NOT be included

    For caller-owned transactions that must include this operation in a
    larger atomic unit, wrap the ENTIRE transaction (including this operation)
    in retry_on_serialization.

    Args:
        operation: A callable that takes a Session as its first argument.
            Must be a complete transaction (all-or-nothing).
        session_factory: A callable that returns a new SQLAlchemy Session.
        max_attempts: Maximum number of attempts (default: 3).
        base_delay: Base delay in seconds for exponential backoff (default: 0.1).
        *args: Additional positional arguments to pass to the operation.
        **kwargs: Additional keyword arguments to pass to the operation.

    Returns:
        The return value of the operation.

    Raises:
        RetryExhausted: If all attempts fail with serialization failures.
        Exception: Any non-serialization exception is propagated immediately.
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
                    # Max attempts exhausted — break to raise RetryExhausted
                    break
            raise
        finally:
            db.close()

    raise RetryExhausted(last_error, max_attempts)
