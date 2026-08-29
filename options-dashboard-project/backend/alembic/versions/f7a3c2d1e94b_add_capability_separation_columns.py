"""Add capability separation columns to broker_connections

Phase 10.2B-6: Separate market data and trading capabilities.

- data_status: tracks whether market data capability is active
- trading_status: tracks whether trading capability is active
- trading_static_ip: per-user static IP for trading
- data_source: how the data token was obtained (analytics_token / oauth_token)

Revision ID: f7a3c2d1e94b
Revises: a0deb75ad22f
Create Date: 2026-08-29 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "f7a3c2d1e94b"
down_revision = "a0deb75ad22f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # data_status: "inactive" | "active" | "expired"
    # Defaults to "inactive" for existing rows (no data capability yet)
    op.add_column(
        "broker_connections",
        sa.Column("data_status", sa.String(20), nullable=False, server_default="inactive"),
    )

    # data_source: "analytics_token" | "oauth_token" | None
    # Indicates which credential type is used for market data
    op.add_column(
        "broker_connections",
        sa.Column("data_source", sa.String(20), nullable=True),
    )

    # trading_status: "inactive" | "active" | "expired"
    # Defaults to "inactive" — existing rows get status from the legacy "status" column
    op.add_column(
        "broker_connections",
        sa.Column("trading_status", sa.String(20), nullable=False, server_default="inactive"),
    )

    # trading_static_ip: per-user static IP for trading (SEBI requirement)
    op.add_column(
        "broker_connections",
        sa.Column("trading_static_ip", sa.String(45), nullable=True),
    )

    # Backfill: existing "connected" rows should have trading_status = "active"
    # and data_status = "active" if they have an analytics token
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
    op.drop_index("ix_broker_connections_trading_status", table_name="broker_connections")
    op.drop_index("ix_broker_connections_data_status", table_name="broker_connections")
    op.drop_column("broker_connections", "trading_static_ip")
    op.drop_column("broker_connections", "trading_status")
    op.drop_column("broker_connections", "data_source")
    op.drop_column("broker_connections", "data_status")
