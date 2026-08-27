"""Alembic environment configuration for StrikeNova.

This env.py is designed to work with both:
1. CLI-driven migrations (alembic upgrade head)
2. Programmatic migration via init_db() (startup)
3. In-memory test databases (via monkeypatched engine)

When a caller sets `_provided_engine`, run_migrations_online() reuses that
engine instead of creating a new one. This is critical for in-memory SQLite
tests where each engine gets its own database.
"""

import os
import sys
import logging

from sqlalchemy import engine_from_config, pool

from alembic import context

# Add backend/ to sys.path so app.* imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models so Base.metadata knows about every table.
# This MUST happen before setting target_metadata.
import app.db as app_db  # noqa: E402
from app.db import Base  # noqa: E402
from app import models  # noqa: E402, F401  — registers tables on Base.metadata
from app.identity import User, UserSession  # noqa: E402, F401  — Phase 10.1 identity tables

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Configure logging for Alembic WITHOUT using fileConfig.
# fileConfig() modifies the root logger globally (adds StreamHandler,
# changes level), which interferes with pytest's caplog fixture.
# Instead, configure only the specific loggers Alembic needs.
logging.getLogger("alembic").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Metadata for autogenerate support — Alembic compares this against
# the live database to detect schema differences.
target_metadata = Base.metadata




def _resolve_database_url() -> str:
    """Resolve the database URL, respecting alembic config first.

    Priority:
    1. sqlalchemy.url set in alembic config (via CLI or set_main_option)
    2. DATABASE_URL environment variable (production / Railway)
    3. Relative sqlite path resolved to backend/paper_journal.db
    """
    # Check if config has a non-default URL set (e.g. from CLI or programmatic call)
    config_url = config.get_main_option("sqlalchemy.url")
    if config_url and not config_url.startswith("driver://"):
        return config_url

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_db_path = os.path.join(backend_dir, "paper_journal.db")
    return f"sqlite:///{default_db_path}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Render ENUM values as VARCHAR for SQLite compatibility
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Check if the caller (e.g. init_db) provided an engine via app.db.
    # This is critical for in-memory SQLite where each engine gets its own DB.
    _pe = getattr(app_db, '_alembic_provided_engine', None) if app_db is not None else None
    if _pe is not None:
        connectable = _pe
    else:
        url = _resolve_database_url()

        # Configure for the dialect
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            configuration = config.get_section(config.config_ini_section, {})
            configuration["sqlalchemy.url"] = url
            connectable = engine_from_config(
                configuration,
                prefix="sqlalchemy.",
                connect_args=connect_args,
                poolclass=pool.NullPool,
            )
        else:
            configuration = config.get_section(config.config_ini_section, {})
            configuration["sqlalchemy.url"] = url
            connectable = engine_from_config(
                configuration,
                prefix="sqlalchemy.",
                poolclass=pool.NullPool,
            )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
