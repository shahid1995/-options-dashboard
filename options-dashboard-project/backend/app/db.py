from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _engine():
    url = settings.DATABASE_URL or "sqlite:///./paper_journal.db"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


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


def init_db():
    """Creates tables on startup. Imported lazily so models can import Base."""
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    Base.metadata.create_all(bind=engine)
    # Phase 6.7: strategy_templates and strategy_template_legs tables are
    # created by create_all above.
    # Phase 6.8B: add V2 dynamic formula columns to strategy_template_legs.
    # All nullable with defaults — idempotent and safe on existing V1 rows.
    ensure_column(engine, "strategy_template_legs", "strike_mode", "VARCHAR(20) DEFAULT 'fixed'")
    ensure_column(engine, "strategy_template_legs", "strike_offset", "INTEGER NULL")
    ensure_column(engine, "strategy_template_legs", "strike_offset_pct", "FLOAT NULL")
    ensure_column(engine, "strategy_template_legs", "target_delta", "FLOAT NULL")
    ensure_column(engine, "strategy_template_legs", "expiry_mode", "VARCHAR(20) DEFAULT 'fixed'")
    ensure_column(engine, "strategy_template_legs", "expiry_dte_min", "INTEGER NULL")
    ensure_column(engine, "strategy_template_legs", "expiry_dte_max", "INTEGER NULL")
    ensure_column(engine, "strategy_template_legs", "formula_version", "INTEGER DEFAULT 1")
    # Phase 6.10: V2 execution audit trail
    ensure_column(engine, "strategy_executions", "execution_metadata", "TEXT NULL")
    # Existing databases predate the Phase 5.0 journal-linkage columns.
    ensure_column(engine, "trades", "strategy_execution_id", "VARCHAR(40) NULL")
    ensure_column(engine, "trades", "client_order_id", "VARCHAR(64) NULL")
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
