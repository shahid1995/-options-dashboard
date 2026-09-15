"""Day41.2 — cross-D1 family lock and S2 evidence

Revision ID: e2b4c6d8f0a1
Revises: 5e2a7b9c3f4d
Create Date: 2026-09-12

Authorized by:
  docs/superpowers/contracts/2026-09-12-strikenova-cross-d1-implementation-authorization.md
Implements (frozen r2 design §7/§12):
  docs/superpowers/specs/2026-09-12-strikenova-cross-d1-s1-s2-implementation-design.md

Schema (exactly the frozen design; nothing more):
  - ``order_family_sync_lock``: D-1 dedicated order-family mutex keyed
    ``(tenant_id, broker, broker_order_id)``.  EXACTLY the three key columns —
    no state, no sequence, no timestamp, no FKs (decision memo: pure mutex).
  - ``broker_sync_idempotency.event_timestamp`` + ``resolution_evidence``:
    durable S2 evidence and UNRESOLVED resolution evidence.
  - ``broker_order_projection.event_timestamp``: durable S2 evidence.

Engine notes (design §7/§20): ``ON CONFLICT DO NOTHING`` atomic first-row
creation is PostgreSQL-native and CockroachDB-compatible (CRDB supports
``ON CONFLICT DO NOTHING``; WHERE-target is deliberately not used).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e2b4c6d8f0a1"
down_revision = "5e2a7b9c3f4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_family_sync_lock",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "broker", "broker_order_id",
            name="pk_order_family_sync_lock",
        ),
    )

    op.add_column(
        "broker_sync_idempotency",
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_sync_idempotency",
        sa.Column("resolution_evidence", sa.Text(), nullable=True),
    )
    op.add_column(
        "broker_order_projection",
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("broker_order_projection", "event_timestamp")
    op.drop_column("broker_sync_idempotency", "resolution_evidence")
    op.drop_column("broker_sync_idempotency", "event_timestamp")
    op.drop_table("order_family_sync_lock")
