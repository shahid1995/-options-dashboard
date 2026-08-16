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
    # Existing databases predate the Phase 5.0 journal-linkage columns.
    ensure_column(engine, "trades", "strategy_execution_id", "VARCHAR(40) NULL")
    ensure_column(engine, "trades", "client_order_id", "VARCHAR(64) NULL")
