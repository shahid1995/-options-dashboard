"""uq_broker_identity_global — global broker-identity ownership index

Revision ID: d9e0f1a2b3c4
Revises: 5e2a7b9c3f4d
Create Date: 2026-09-14

Authorized by:
  docs/architecture/UPSTOX_IDENTITY_LINKING_DESIGN.md (§11, §14, §17.3)
Parent revision (f461125 follow-up): the committed Alembic chain head at
the time of authoring was 5e2a7b9c3f4d (the merge of the google-sub index
with the main chain). An earlier draft parented this revision onto an
UNCOMMITTED Day41.2 file, which produced a dangling down_revision on any
clean checkout (staging deploy dep-dajt61ek1f9s739be460 failed with
``KeyError: 'e2b4c6d8f0a1'`` at startup); re-parented so the committed
tree's migration graph is self-contained. If/when the Day41.2 chain is
committed upstream, a later merge revision can restore that ancestry.

Design SQL, extended for the SECOND per-user sentinel:

    CREATE UNIQUE INDEX uq_broker_identity_global
    ON broker_connections (broker, broker_account_id)
    WHERE broker_account_id NOT IN ('pending', 'data-only')

Execution notes (staging-verified):
1. The index is created via op.execute() with the COMPLETE partial-index
   DDL instead of op.create_index(dialect_where=...). The first staging
   execution proved the sqlalchemy-cockroachdb dialect SILENTLY DROPS the
   cockroachdb_where kwarg (deploys dep-dajteaeq1p3s739g9i1g /
   dep-dajti367bikc73df4ngg failed with a full unique index — error
   "failed to ingest index entries during backfill: duplicate key value
   violates unique constraint ... ('UPSTOX','data-only')"), so dialect
   kwargs cannot be trusted for this guarantee.
2. The predicate uses chained AND <> comparisons rather than NOT IN:
   NOT IN has dialect-ambiguous precedence/parenthesization when embedded
   in a partial-index WHERE across engines, while chained <> is identical
   on PostgreSQL, CockroachDB >= 22.2 (partial indexes), and SQLite.
3. 'pending' and 'data-only' are PER-USER sentinels (store_credentials /
   store_analytics_token), never real broker account identities; multiple
   users' sentinel rows legitimately coexist (proven live on staging CRDB)
   and stay outside the global ownership guarantee. Live UCC identities
   remain globally unique — the database is the arbiter of ownership.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "5e2a7b9c3f4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_broker_identity_global"
_TABLE = "broker_connections"
_PREDICATE = (
    "broker_account_id <> 'pending' AND broker_account_id <> 'data-only'"
)


def upgrade() -> None:
    """Create the global broker-identity ownership partial unique index."""
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX_NAME} "
        f"ON {_TABLE} (broker, broker_account_id) "
        f"WHERE {_PREDICATE}"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
