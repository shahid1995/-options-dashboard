"""day41: add broker_raw_observation (durable raw-ingress, Day40.6 §2)

Revision ID: a7c1d9e4f2b8
Revises: f7aa24156f6d
Create Date: 2026-09-10

Adds the Phase-1 durable raw-observation table:
- broker_raw_observation: BYTEA-preserving raw provider payload — the
  authoritative evidence record.  Committed in a dedicated Phase-1
  transaction BEFORE any normalization/classification (Day40.6 §1);
  downstream failure can never erase it (Invariants AB/AC).

(d1, content_fingerprint) is deliberately NON-unique: raw observations are
never delivery-deduped on (D1, FPv2) — fill lanes require admissible
delivery evidence and order-lane dedup happens at broker_sync_observation
(Day40.5 §5.2 / Day40.6 §5.2).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c1d9e4f2b8"
down_revision: Union[str, None] = "f7aa24156f6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "broker_raw_observation",
        sa.Column("raw_observation_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        # BYTEA on PostgreSQL / BLOB on SQLite — EXACT provider bytes.
        sa.Column("raw_payload", sa.LargeBinary(), nullable=False),
        sa.Column("delivery_evidence", sa.Text(), nullable=True),
        sa.Column("provider_order_id", sa.String(length=128), nullable=True),
        sa.Column("provider_trade_id", sa.String(length=128), nullable=True),
        sa.Column("d1", sa.String(length=64), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("raw_observation_id"),
    )
    op.create_index(
        "ix_broker_raw_observation_tenant_id",
        "broker_raw_observation",
        ["tenant_id"],
        unique=False,
    )
    # Non-unique by design (see docstring).
    op.create_index(
        "ix_broker_raw_observation_d1_fp",
        "broker_raw_observation",
        ["tenant_id", "broker", "d1", "content_fingerprint"],
        unique=False,
    )
    # d1 lookup index (Day41.1 correction: ORM declares index=True on the d1
    # column; the original migration omitted this index — field-matrix finding).
    op.create_index(
        "ix_broker_raw_observation_d1",
        "broker_raw_observation",
        ["d1"],
        unique=False,
    )
    op.create_index(
        "ix_broker_raw_observation_processing",
        "broker_raw_observation",
        ["processing_status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_broker_raw_observation_processing", table_name="broker_raw_observation")
    op.drop_index("ix_broker_raw_observation_d1_fp", table_name="broker_raw_observation")
    op.drop_index("ix_broker_raw_observation_d1", table_name="broker_raw_observation")
    op.drop_index("ix_broker_raw_observation_tenant_id", table_name="broker_raw_observation")
    op.drop_table("broker_raw_observation")
