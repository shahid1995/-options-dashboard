"""day39: add broker-sync idempotency, projection, and sequence anchor tables

Revision ID: 9b675f8a3af0
Revises: e8f9a0b1c2d3
Create Date: 2026-09-08 15:09:08.251209

Adds durable broker-sync persistence tables for Day 39 Task 2:
- broker_sync_idempotency: durable idempotency record (canonical_id PK)
- broker_order_projection: normalized broker-order state
- broker_sync_sequence_anchor: durable monotonic sequence for ordering validation
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b675f8a3af0"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "broker_sync_idempotency",
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=True),
        sa.Column("canonical_sequence", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_version", sa.String(length=16), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=256), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("canonical_id"),
    )
    op.create_index("ix_broker_sync_idempotency_tenant", "broker_sync_idempotency", ["tenant_id"], unique=False)
    op.create_index("ix_broker_sync_idempotency_broker_order_id", "broker_sync_idempotency", ["broker_order_id"], unique=False)
    op.create_index("ix_broker_sync_idempotency_provider_event_id", "broker_sync_idempotency", ["provider_event_id"], unique=False)

    op.create_table(
        "broker_order_projection",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=True),
        sa.Column("cumulative_filled", sa.Integer(), nullable=False),
        sa.Column("remaining_quantity", sa.Integer(), nullable=True),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column("last_fill_price", sa.Float(), nullable=True),
        sa.Column("last_fill_quantity", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fill_count", sa.Integer(), nullable=False),
        sa.Column("last_fill_id", sa.String(length=128), nullable=True),
        sa.Column("canonical_sequence", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broker_order_projection_tenant_broker_order", "broker_order_projection", ["tenant_id", "broker", "broker_order_id"], unique=False)
    op.create_index("ix_broker_order_projection_canonical_id", "broker_order_projection", ["canonical_id"], unique=False)

    op.create_table(
        "broker_sync_sequence_anchor",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False),
        sa.Column("broker_order_id", sa.String(length=128), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "broker", "broker_order_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("broker_sync_sequence_anchor")
    op.drop_index("ix_broker_order_projection_canonical_id", table_name="broker_order_projection")
    op.drop_index("ix_broker_order_projection_tenant_broker_order", table_name="broker_order_projection")
    op.drop_table("broker_order_projection")
    op.drop_index("ix_broker_sync_idempotency_provider_event_id", table_name="broker_sync_idempotency")
    op.drop_index("ix_broker_sync_idempotency_broker_order_id", table_name="broker_sync_idempotency")
    op.drop_index("ix_broker_sync_idempotency_tenant", table_name="broker_sync_idempotency")
    op.drop_table("broker_sync_idempotency")
