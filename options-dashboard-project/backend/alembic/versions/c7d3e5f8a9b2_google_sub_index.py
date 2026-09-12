"""google_sub unique partial index

Revision ID: c7d3e5f8a9b2
Revises: b8c9f1d2e34a
Create Date: 2026-09-12 16:00:00.000000

Creates the unique partial index on google_sub after the column has been
committed, ensuring CockroachDB compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7d3e5f8a9b2"
down_revision: Union[str, None] = "b8c9f1d2e34a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create unique partial index on google_sub."""
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.create_index(
            "ix_users_google_sub",
            "users",
            ["google_sub"],
            unique=True,
            postgresql_where="google_sub IS NOT NULL",
        )
    elif dialect == "sqlite":
        # SQLite supports partial indexes with WHERE clause
        op.create_index(
            "ix_users_google_sub",
            "users",
            ["google_sub"],
            unique=True,
            sqlite_where="google_sub IS NOT NULL",
        )
    elif dialect == "cockroachdb":
        # CockroachDB supports partial indexes with WHERE clause
        op.create_index(
            "ix_users_google_sub",
            "users",
            ["google_sub"],
            unique=True,
            cockroachdb_where="google_sub IS NOT NULL",
        )
    else:
        # Fallback: create a regular unique index (may not handle NULLs ideally)
        op.create_index(
            "ix_users_google_sub",
            "users",
            ["google_sub"],
            unique=True,
        )


def downgrade() -> None:
    """Drop google_sub unique partial index."""
    op.drop_index("ix_users_google_sub", table_name="users")
