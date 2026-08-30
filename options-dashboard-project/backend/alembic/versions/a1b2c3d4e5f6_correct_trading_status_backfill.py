"""Correct trading_status backfill for legacy connected rows.

The original migration f7a3c2d1e94b set trading_status='active' for all
rows with status='connected'. This is incorrect: broker OAuth connected
does not mean trading-capable.

This corrective migration resets ALL trading_status to 'inactive'.
Trading capability requires explicit authorization (Phase 10.2B-6).
No magic broker_account_id values are used to encode capabilities.

Revision ID: a1b2c3d4e5f6
Revises: f7a3c2d1e94b
Create Date: 2026-08-30 18:00:00.000000
"""
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "b8c9f1d2e34a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reset ALL trading_status to 'inactive'.
    # The original backfill incorrectly set trading_status='active' for
    # status='connected' rows. Broker OAuth connected != trading-capable.
    # Trading requires explicit authorization (Phase 10.2B-6 design decision).
    # No magic broker_account_id values — trading capability is not encoded
    # via account IDs.
    op.execute(
        """
        UPDATE broker_connections
        SET trading_status = 'inactive'
        WHERE trading_status = 'active'
        """
    )


def downgrade() -> None:
    # Cannot safely reverse — we don't know which rows were legitimately
    # trading-enabled before this correction.
    pass
