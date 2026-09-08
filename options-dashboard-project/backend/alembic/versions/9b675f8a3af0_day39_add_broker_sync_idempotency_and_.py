"""day39: add broker-sync idempotency and projection tables

Revision ID: 9b675f8a3af0
Revises: merge_day38_gex
Create Date: 2026-09-08 15:09:08.251209
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b675f8a3af0'
down_revision: Union[str, None] = 'merge_day38_gex'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "broker_sync_idempotency",
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column("canonical_sequence", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_version", sa.String(length=16), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("canonical_id"),
    )
    op.create_index(
        "ix_broker_sync_idempotency_tenant_id",
        "broker_sync_idempotency",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_broker_sync_idempotency_broker",
        "broker_sync_idempotency",
        ["broker"],
        unique=False,
    )
    op.create_index(
        "ix_broker_sync_idempotency_broker_order_id",
        "broker_sync_idempotency",
        ["broker_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_broker_sync_idempotency_provider_event_id",
        "broker_sync_idempotency",
        ["provider_event_id"],
        unique=False,
    )

    op.create_table(
        "broker_order_projection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=True),
        sa.Column("cumulative_filled", sa.Integer(), nullable=False),
        sa.Column("remaining_quantity", sa.Integer(), nullable=True),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column("last_fill_price", sa.Float(), nullable=True),
        sa.Column("last_fill_quantity", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        sa.Column("is_terminal", sa.Boolean(), nullable=False),
        sa.Column("fill_count", sa.Integer(), nullable=False),
        sa.Column("last_fill_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "broker",
            "broker_order_id",
            "canonical_id",
            name="uq_broker_projection_tenant_broker_order_canonical",
        ),
        sa.UniqueConstraint("canonical_id", name="uq_broker_projection_canonical_id"),
    )
    op.create_index(
        "ix_broker_order_projection_tenant_id",
        "broker_order_projection",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_broker_order_projection_broker",
        "broker_order_projection",
        ["broker"],
        unique=False,
    )
    op.create_index(
        "ix_broker_order_projection_broker_order_id",
        "broker_order_projection",
        ["broker_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_broker_order_projection_canonical_id",
        "broker_order_projection",
        ["canonical_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_broker_order_projection_canonical_id",
        table_name="broker_order_projection",
    )
    op.drop_index(
        "ix_broker_order_projection_broker_order_id",
        table_name="broker_order_projection",
    )
    op.drop_index(
        "ix_broker_order_projection_broker",
        table_name="broker_order_projection",
    )
    op.drop_index(
        "ix_broker_order_projection_tenant_id",
        table_name="broker_order_projection",
    )
    op.drop_table("broker_order_projection")

    op.drop_index(
        "ix_broker_sync_idempotency_provider_event_id",
        table_name="broker_sync_idempotency",
    )
    op.drop_index(
        "ix_broker_sync_idempotency_broker_order_id",
        table_name="broker_sync_idempotency",
    )
    op.drop_index(
        "ix_broker_sync_idempotency_broker",
        table_name="broker_sync_idempotency",
    )
    op.drop_index(
        "ix_broker_sync_idempotency_tenant_id",
        table_name="broker_sync_idempotency",
    )
    op.drop_table("broker_sync_idempotency")
