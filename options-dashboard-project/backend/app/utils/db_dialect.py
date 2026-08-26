"""Database dialect utilities for SQLite/PostgreSQL portability (Phase 9D).

Provides a dialect-aware ``dialect_insert`` function that returns the correct
SQLAlchemy dialect-specific ``insert()`` construct based on the engine's
dialect. This allows ``on_conflict_do_update()`` to work on both SQLite
and PostgreSQL without hardcoding the dialect at each call site.
"""

from __future__ import annotations

from sqlalchemy import Table
from sqlalchemy.engine import Engine


def dialect_insert(engine: Engine, table: Table):
    """Return a dialect-specific insert construct for the given table.

    Uses PostgreSQL's ``insert()`` for PostgreSQL databases and SQLite's
    ``insert()`` for SQLite databases. Both support ``on_conflict_do_update()``.

    For other dialects (MySQL, etc.), falls back to generic ``insert()``
    which does NOT support ``on_conflict_do_update`` — callers must handle
    that case separately.
    """
    dialect_name = engine.dialect.name

    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        return insert(table)
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        return insert(table)
    else:
        # Fallback: generic insert (no on_conflict_do_update)
        from sqlalchemy import insert
        return insert(table)
