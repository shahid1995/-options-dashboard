import os

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Database path resolution
# ---------------------------------------------------------------------------
#
# Phase 7.20 audit discovered that the previous relative path
# ("sqlite:///./paper_journal.db") resolved differently depending on
# the process working directory, causing data loss across server
# restarts and CLI invocations.
#
# FIX: When DATABASE_URL is not set, resolve relative to this file's
# parent directory (backend/), so the database always lives at
#   backend/paper_journal.db
# regardless of where Python/Uvicorn/CLI is launched from.
#
# When DATABASE_URL IS set (e.g. Railway PostgreSQL), use it as-is.
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_DIR, "paper_journal.db")


def _engine():
    if settings.DATABASE_URL:
        url = settings.DATABASE_URL
    else:
        # Absolute file path wrapped in sqlite:/// URI
        url = f"sqlite:///{_DEFAULT_DB_PATH}"
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        eng = create_engine(url, connect_args=connect_args)
        # Phase 7.23B: Switch SQLite to WAL journal mode for crash safety.
        @event.listens_for(eng, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    else:
        # Phase 9E: Production PostgreSQL configuration
        eng = create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )

    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA synchronous=NORMAL")

    return eng


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_database_path() -> str:
    """Return the absolute filesystem path of the active database."""
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    return _DEFAULT_DB_PATH


def get_db():
    """FastAPI dependency: yields a database session, closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _existing_columns(engine, table: str) -> set[str]:
    """Names of the columns currently present on ``table`` (SQLite or Postgres)."""
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            return {r[1] for r in rows}
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        ).fetchall()
        return {r[0] for r in rows}


def ensure_column(engine, table: str, column: str, ddl: str) -> None:
    """Idempotent lightweight migration: add ``column`` if the table lacks it.

    ``create_all`` creates missing *tables* but never alters existing ones.
    Phase 5.0 added nullable columns to the pre-existing ``trades`` table;
    this helper adds them to existing databases at startup. New tables are
    still handled entirely by ``Base.metadata.create_all``.
    """
    if not _existing_columns(engine, table):
        return  # table does not exist yet; create_all will define it fully
    if column not in _existing_columns(engine, table):
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _run_alembic_migrations() -> None:
    """Run Alembic migrations against the current engine.

    Called from init_db() to apply versioned schema migrations at startup.
    This is the PRIMARY schema management path — Alembic owns the
    authoritative schema definition.

    For existing databases created by the old ``create_all`` path, run
    ``alembic stamp head`` once to mark them as current before deploying
    this code.
    """
    import logging
    from alembic.config import Config
    from alembic import command

    logger = logging.getLogger(__name__)
    alembic_cfg = Config("alembic.ini")
    # Override sqlalchemy.url to use the current engine's URL so tests
    # with monkeypatched engines still work correctly.
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations applied successfully")


# ---------------------------------------------------------------------------
# TRANSITIONAL SCHEMA ARCHITECTURE (Phase 10.1A)
# ---------------------------------------------------------------------------
#
# The current startup sequence is a TRANSITIONAL architecture:
#
#   1. Alembic upgrade head      — versioned, authoritative
#   2. create_all()              — safety net (transitional)
#   3. ensure_column()           — legacy column additions (transitional)
#   4. backfill + indexes        — data migrations
#
# TARGET architecture (to be completed in future phases):
#
#   Application start
#       |
#       v
#   Alembic upgrade head    — ONLY schema management mechanism
#       |
#       v
#   No request-path DDL.
#   No create_all().
#   No ensure_column().
#
# The create_all() and ensure_column() calls below exist because:
#   - Alembic baseline was just introduced; all existing tables ARE
#     captured, but the safety net protects against edge cases.
#   - ensure_column() calls cover columns added in Phases 5.0-8F
#     that predate Alembic and have not yet been converted to
#     proper Alembic migrations.
#
# These will be removed in Phase 10.1B when all legacy columns
# are migrated to Alembic.
#
# PRODUCTION SAFETY: create_all() and ensure_column() only run during
# application startup (init_db), NEVER during request handling.
# The auth path was cleaned in Phase 10.1A to remove all DDL.
# ---------------------------------------------------------------------------


def init_db():
    """Initialize database schema on application startup.

    **TRANSITIONAL ARCHITECTURE** — This function runs a multi-step
    schema initialization that will be simplified in future phases.

    Current sequence:
      1. Alembic upgrade head (authoritative, versioned)
      2. create_all() (safety net for unmigrated tables — transitional)
      3. ensure_column() (legacy column additions — transitional)
      4. backfill + indexes (data migrations)

    Target sequence (Phase 10.1B+):
      1. Alembic upgrade head (sole schema management)

    This function is called ONCE at application startup from the
    FastAPI lifespan handler. It is NEVER called during request
    processing.
    """
    import logging
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    logger = logging.getLogger(__name__)

    # Step 1: Alembic migrations (authoritative schema management).
    # This MUST succeed — if it fails, the application should not start.
    _run_alembic_migrations()

    # Step 2: create_all() safety net (TRANSITIONAL — will be removed).
    # Currently all 24 Base.metadata tables ARE in the Alembic baseline,
    # so this is effectively a no-op. It remains as a safety net during
    # the transition period. Once all tables are confirmed in migrations
    # and the ensure_column() calls are converted, this line should be
    # removed.
    #
    # IMPORTANT: This MUST NOT run during request handling. It only runs
    # during application startup via init_db().
    Base.metadata.create_all(bind=engine)
    # -----------------------------------------------------------------------
    # LEGACY ensure_column() CALLS (TRANSITIONAL — will be removed in 10.1B)
    # -----------------------------------------------------------------------
    #
    # These 15 ensure_column() calls add columns to existing tables that
    # were introduced in Phases 5.0-8F, before Alembic was adopted.
    # They are all nullable with defaults, idempotent, and safe.
    #
    # INVENTORY (see docs/PHASE_10_1A_DATABASE_MIGRATIONS.md §ensure_column):
    #
    # Table                     Column               Phase  In Alembic?  Migration needed?
    # ------------------------- -------------------- ------ ------------ -----------------
    # strategy_template_legs    strike_mode           6.8B   YES (enum)   NO — in baseline
    # strategy_template_legs    strike_offset         6.8B   YES          NO — in baseline
    # strategy_template_legs    strike_offset_pct     6.8B   YES          NO — in baseline
    # strategy_template_legs    target_delta          6.8B   YES          NO — in baseline
    # strategy_template_legs    expiry_mode           6.8B   YES          NO — in baseline
    # strategy_template_legs    expiry_dte_min        6.8B   YES          NO — in baseline
    # strategy_template_legs    expiry_dte_max        6.8B   YES          NO — in baseline
    # strategy_template_legs    formula_version       6.8B   YES          NO — in baseline
    # strategy_executions       execution_metadata    6.10   YES          NO — in baseline
    # strategy_executions       tags                  7.0    YES          NO — in baseline
    # strategy_executions       notes                 7.0    YES          NO — in baseline
    # trades                    strategy_execution_id 5.0    YES          NO — in baseline
    # trades                    client_order_id       5.0    YES          NO — in baseline
    # gex_snapshots             sweep_data            7.6    YES          NO — in baseline
    # gex_snapshots             owner_id              8F     YES          NO — in baseline
    #
    # ALL of these columns are already represented in the Alembic baseline
    # migration (d3eb45a2e046). The ensure_column() calls are redundant
    # for new databases. They exist solely for pre-existing databases that
    # were created before the Alembic baseline and have not yet been
    # stamped. Once production databases are stamped, these can be removed.
    #
    # Phase 10.1B action: Convert these to a single Alembic migration that
    # is a no-op (columns already exist), then remove these calls.
    # -----------------------------------------------------------------------
    ensure_column(engine, "strategy_template_legs", "strike_mode", "VARCHAR(20) DEFAULT 'fixed'")
    ensure_column(engine, "strategy_template_legs", "strike_offset", "INTEGER NULL")
    ensure_column(engine, "strategy_template_legs", "strike_offset_pct", "FLOAT NULL")
    ensure_column(engine, "strategy_template_legs", "target_delta", "FLOAT NULL")
    ensure_column(engine, "strategy_template_legs", "expiry_mode", "VARCHAR(20) DEFAULT 'fixed'")
    ensure_column(engine, "strategy_template_legs", "expiry_dte_min", "INTEGER NULL")
    ensure_column(engine, "strategy_template_legs", "expiry_dte_max", "INTEGER NULL")
    ensure_column(engine, "strategy_template_legs", "formula_version", "INTEGER DEFAULT 1")
    ensure_column(engine, "strategy_executions", "execution_metadata", "TEXT NULL")
    ensure_column(engine, "strategy_executions", "tags", "TEXT NULL")
    ensure_column(engine, "strategy_executions", "notes", "TEXT NULL")
    ensure_column(engine, "trades", "strategy_execution_id", "VARCHAR(40) NULL")
    ensure_column(engine, "trades", "client_order_id", "VARCHAR(64) NULL")
    ensure_column(engine, "gex_snapshots", "sweep_data", "TEXT NULL")
    ensure_column(engine, "gex_snapshots", "owner_id", "VARCHAR(128) NULL")
    # Phase 6.5.0.1: conservative one-time backfill of strategy-leg
    # attribution for pre-existing, provably unambiguous executions.
    # Idempotent — rows already present are never duplicated.
    from app.services.leg_exposure import backfill_all_exposures

    # Create a session bound to the *current* engine variable so that
    # backfill_all_exposures always queries the same database that create_all
    # just migrated — even when engine is monkeypatched in tests.
    session = sessionmaker(bind=engine)()
    try:
        backfill_all_exposures(session)
    finally:
        session.close()

    # Phase 7.24.1: Create indexes for pipeline infrastructure tables.
    # Uses CREATE INDEX IF NOT EXISTS for idempotent execution.
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            for stmt in [
                "CREATE INDEX IF NOT EXISTS ix_ingestion_log_operation_status ON ingestion_log (operation, status)",
                "CREATE INDEX IF NOT EXISTS ix_ingestion_log_completed_at ON ingestion_log (completed_at)",
                "CREATE INDEX IF NOT EXISTS ix_data_completeness_status ON data_completeness (status)",
                "CREATE INDEX IF NOT EXISTS ix_ingestion_checkpoint_status ON ingestion_checkpoint (pipeline, status)",
            ]:
                conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# Database health check (Phase 7.21)
# ---------------------------------------------------------------------------

# Tables that should exist in the historical-data schema.
_HISTORICAL_TABLES = [
    "nifty_candles",
    "contract_specs",
    "option_candles",
    "option_greeks",
]


def check_database_health() -> dict:
    """Return a diagnostic snapshot of the production database.

    Designed to be called before any backfill to confirm the database
    is accessible, correctly located, and has the expected schema.

    Returns
    -------
    dict
        A machine-readable health report with path, size, row counts,
        and accessibility status.
    """
    from sqlalchemy import inspect as sa_inspect, func, select

    db_path = get_database_path()
    report: dict = {
        "database_path": db_path,
        "file_exists": False,
        "file_size_bytes": 0,
        "accessible": False,
        "tables_present": [],
        "tables_missing": [],
        "row_counts": {},
        "oldest_record": None,
        "newest_record": None,
    }

    # File check
    if os.path.isfile(db_path):
        report["file_exists"] = True
        report["file_size_bytes"] = os.path.getsize(db_path)

    # Schema check
    try:
        insp = sa_inspect(engine)
        existing_tables = set(insp.get_table_names())
        report["tables_present"] = sorted(
            t for t in _HISTORICAL_TABLES if t in existing_tables
        )
        report["tables_missing"] = sorted(
            t for t in _HISTORICAL_TABLES if t not in existing_tables
        )
    except Exception as e:
        report["schema_error"] = str(e)
        return report

    # Row counts and date range
    db = SessionLocal()
    try:
        from app.models import NiftyCandle, ContractSpec, OptionCandle, OptionGreeks

        for label, model in [
            ("nifty_candles", NiftyCandle),
            ("contract_specs", ContractSpec),
            ("option_candles", OptionCandle),
            ("option_greeks", OptionGreeks),
        ]:
            count = db.scalar(select(func.count(model.id))) or 0
            report["row_counts"][label] = count

        # Date range from nifty_candles (if any data)
        nifty_oldest = db.scalar(
            select(NiftyCandle.open_time).order_by(NiftyCandle.open_time.asc()).limit(1)
        )
        nifty_newest = db.scalar(
            select(NiftyCandle.open_time).order_by(NiftyCandle.open_time.desc()).limit(1)
        )
        if nifty_oldest:
            report["oldest_record"] = str(nifty_oldest)
        if nifty_newest:
            report["newest_record"] = str(nifty_newest)

        report["accessible"] = True
    except Exception as e:
        report["access_error"] = str(e)
    finally:
        db.close()

    return report
