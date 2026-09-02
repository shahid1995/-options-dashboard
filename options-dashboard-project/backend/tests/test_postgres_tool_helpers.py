from __future__ import annotations

from unittest.mock import patch


def test_contract_metadata_backfill_uses_empty_connect_args_for_postgres():
    """PostgreSQL must not receive SQLite-only check_same_thread options."""
    from app.tools import contract_metadata_backfill

    with patch.object(contract_metadata_backfill.settings, "DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/db"):
        with patch.object(contract_metadata_backfill, "create_engine") as create_engine:
            create_engine.return_value = object()
            with patch.object(contract_metadata_backfill.Base.metadata, "create_all"):
                with patch.object(contract_metadata_backfill, "sessionmaker"):
                    contract_metadata_backfill._get_session()
            create_engine.assert_called_once_with(
                "postgresql+psycopg://user:pass@host:5432/db",
                connect_args={},
            )


def test_contract_metadata_backfill_keeps_sqlite_connect_args():
    """SQLite local tooling retains its check_same_thread compatibility."""
    from app.tools import contract_metadata_backfill

    with patch.object(contract_metadata_backfill.settings, "DATABASE_URL", "sqlite:///tmp/test.db"):
        with patch.object(contract_metadata_backfill, "create_engine") as create_engine:
            create_engine.return_value = object()
            with patch.object(contract_metadata_backfill.Base.metadata, "create_all"):
                with patch.object(contract_metadata_backfill, "sessionmaker"):
                    contract_metadata_backfill._get_session()
            create_engine.assert_called_once_with(
                "sqlite:///tmp/test.db",
                connect_args={"check_same_thread": False},
            )
