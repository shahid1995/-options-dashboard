"""Capability separation backfill and indexes (DML + indexes)

Phase 10.2B-6: Separate market data and trading capabilities.

This migration adds the backfill UPDATEs and indexes for the capability
separation columns added in revision f7a3c2d1e94b.

NOTE: This is intentionally a separate revision from f7a3c2d1e94b because
CockroachDB does not expose DDL changes to subsequent DML within the same
transaction. The DDL (ADD COLUMN) must be committed first, then the DML
(UPDATE) can see the new columns.

Revision ID: 9e4d8c2a1f7b
Revises: f7a3c2d1e94b
Create Date: 2026-09-12 15:00:00.000000
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "9e4d8c2a1f7b"
down_revision = "f7a3c2d1e94b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill capability separation data and create indexes."""
    # Backfill: existing "connected" rows should have trading_status = "active"
    op.execute(
        """
        UPDATE broker_connections
        SET trading_status = 'active'
        WHERE status = 'connected'
        """
    )
    op.execute(
        """
        UPDATE broker_connections
        SET data_status = 'active',
            data_source = CASE
                WHEN broker_analytics_token_encrypted IS NOT NULL THEN 'analytics_token'
                ELSE 'oauth_token'
            END
        WHERE status = 'connected'
          AND (broker_analytics_token_encrypted IS NOT NULL
               OR broker_api_key_encrypted IS NOT NULL)
        """
    )

    # Create index for efficient data capability lookups
    op.create_index(
        "ix_broker_connections_data_status",
        "broker_connections",
        ["data_status"],
    )
    op.create_index(
        "ix_broker_connections_trading_status",
        "broker_connections",
        ["trading_status"],
    )


def downgrade() -> None:
    """Drop capability separation indexes."""
    op.drop_index("ix_broker_connections_trading_status", table_name="broker_connections")
    op.drop_index("ix_broker_connections_data_status", table_name="broker_connections")
