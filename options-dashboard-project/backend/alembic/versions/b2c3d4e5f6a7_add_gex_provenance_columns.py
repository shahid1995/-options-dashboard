"""Add connection_id and data_source to gex_snapshots for provenance.

Phase 10.2B-6: USER-SCOPED GEX requires explicit ownership provenance:
- owner_id: StrikeNova user ID (already exists)
- connection_id: BrokerConnection ID that authorized the capture
- data_source: "analytics_token" or "broker_oauth"

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gex_snapshots",
        sa.Column("connection_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "gex_snapshots",
        sa.Column("data_source", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gex_snapshots", "data_source")
    op.drop_column("gex_snapshots", "connection_id")
