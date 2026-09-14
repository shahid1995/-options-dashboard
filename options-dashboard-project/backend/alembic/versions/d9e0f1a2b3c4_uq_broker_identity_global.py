"""uq_broker_identity_global — global broker-identity ownership index

Revision ID: d9e0f1a2b3c4
Revises: e2b4c6d8f0a1
Create Date: 2026-09-14

Authorized by:
  docs/architecture/UPSTOX_IDENTITY_LINKING_DESIGN.md (§11, §14, §17.3)
Implements (exact design SQL):

    CREATE UNIQUE INDEX uq_broker_identity_global
    ON broker_connections (broker, broker_account_id)
    WHERE broker_account_id <> 'pending'

Purpose (design Invariants 1/7): one broker identity maps to at most one
StrikeNova user. The partial predicate preserves the 'pending' sentinel
semantics (any user may hold one pending pre-OAuth connection per broker)
while making the database the arbiter of global ownership for live
connections.

Pre-condition verified before authoring (duplicate-ownership audit,
2026-09-14, local dev DB): zero (broker, broker_account_id) groups with
more than one distinct owner among live (non-pending) rows. If a target
database contains duplicate ownership, alembic upgrade will fail on the
CREATE UNIQUE INDEX — remediation is a deliberate human decision, never
an automatic reassignment.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "e2b4c6d8f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Partial-index predicate. Must be a text() clause: on SQLAlchemy 2.0.x the
# SQLite/PostgreSQL dialects compile a raw str where-clause via
# _compiler_dispatch and fail with AttributeError (verified 2026-09-14;
# same convention as c7d3e5f8a9b2_google_sub_index).
_PREDICATE = "broker_account_id <> 'pending'"


def upgrade() -> None:
    """Create the global broker-identity ownership partial unique index."""
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.create_index(
            "uq_broker_identity_global",
            "broker_connections",
            ["broker", "broker_account_id"],
            unique=True,
            postgresql_where=text(_PREDICATE),
        )
    elif dialect == "cockroachdb":
        # CockroachDB >= 22.2 supports partial indexes; the sqlalchemy-
        # cockroachdb dialect dispatches dialect-specific kwargs via the
        # 'cockroachdb_' prefix (same pattern as uq_users google_sub index).
        op.create_index(
            "uq_broker_identity_global",
            "broker_connections",
            ["broker", "broker_account_id"],
            unique=True,
            cockroachdb_where=text(_PREDICATE),
        )
    else:
        # SQLite supports partial indexes natively (validated by
        # tests/test_identity_linking.py::test_global_partial_index_*).
        op.create_index(
            "uq_broker_identity_global",
            "broker_connections",
            ["broker", "broker_account_id"],
            unique=True,
            sqlite_where=text(_PREDICATE),
        )


def downgrade() -> None:
    op.drop_index("uq_broker_identity_global", table_name="broker_connections")
