"""Alembic environment configuration for StrikeNova.

This env.py supports:
1. CLI-driven migrations (alembic upgrade head)
2. Programmatic migrations during application startup
3. In-memory SQLite test databases via Config.attributes['connectable']
4. SQLite and PostgreSQL dialects without applying SQLite-specific batch
   behavior to PostgreSQL migrations.
"""

from __future__ import annotations

import logging
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add backend/ to sys.path so app.* imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models so Base.metadata knows about every table.
from app.db import Base, normalize_database_url  # noqa: E402
from app import models  # noqa: E402, F401
from app.identity import User, UserSession, BrokerConnection, BrokerToken  # noqa: E402, F401

config = context.config

# Keep Alembic logging isolated so pytest/caplog behavior is unaffected.
logging.getLogger("alembic").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Resolve the database URL used by Alembic.

    Priority:
    1. sqlalchemy.url supplied by the caller/configuration
    2. DATABASE_URL environment variable
    3. backend/paper_journal.db SQLite fallback
    """
    config_url = config.get_main_option("sqlalchemy.url")
    if config_url and not config_url.startswith("driver://"):
        return normalize_database_url(config_url)

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return normalize_database_url(db_url)

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_db_path = os.path.join(backend_dir, "paper_journal.db")
    return f"sqlite:///{default_db_path}"


def _render_as_batch(url: str) -> bool:
    """Use Alembic batch mode only for SQLite schema operations."""
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Run migrations in offline mode using the resolved dialect."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_render_as_batch(url),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations online using the supplied or newly-created engine."""
    connectable = config.attributes.get("connectable")
    if connectable is None:
        url = _resolve_database_url()
        configuration = config.get_section(config.config_ini_section, {})
        configuration["sqlalchemy.url"] = url

        if url.startswith("sqlite"):
            connectable = engine_from_config(
                configuration,
                prefix="sqlalchemy.",
                connect_args={"check_same_thread": False},
                poolclass=pool.NullPool,
            )
        else:
            connectable = engine_from_config(
                configuration,
                prefix="sqlalchemy.",
                poolclass=pool.NullPool,
            )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
