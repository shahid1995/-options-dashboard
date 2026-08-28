"""add_broker_connection_foundation

Revision ID: 125e1807df8d
Revises: d3eb45a2e046
Create Date: 2026-08-28 15:39:14.221533

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '125e1807df8d'
down_revision: Union[str, None] = 'd3eb45a2e046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Phase 10.2B-1: Broker Connection Foundation.
    Creates broker_connections and broker_tokens tables,
    adds broker_connection_id to user_sessions.
    """
    # 1. broker_connections — persistent broker relationship + per-user credentials
    op.create_table(
        'broker_connections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('broker', sa.String(32), nullable=False),
        sa.Column('broker_account_id', sa.String(128), nullable=False),
        sa.Column('display_label', sa.String(160), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('status', sa.String(20), server_default='connected', nullable=False),
        sa.Column('capability_mode', sa.String(20), server_default='trading', nullable=False),
        # Per-user broker credentials (encrypted — AD-2, AD-3)
        sa.Column('broker_api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('broker_api_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('broker_analytics_token_encrypted', sa.Text(), nullable=True),
        sa.Column('broker_redirect_uri', sa.Text(), nullable=True),
        sa.Column('broker_static_ip', sa.String(45), nullable=True),
        # Provider-specific metadata
        sa.Column('app_type', sa.String(32), nullable=True),
        sa.Column('provider_metadata_json', sa.Text(), server_default='{}', nullable=False),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('connected_at', sa.DateTime(), nullable=False),
        sa.Column('disconnected_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'broker', 'broker_account_id', name='uq_broker_connection'),
    )
    op.create_index('ix_broker_connections_user_id', 'broker_connections', ['user_id'])
    op.create_index('ix_broker_connections_broker', 'broker_connections', ['broker'])

    # 2. broker_tokens — session-scoped broker token (encrypted)
    op.create_table(
        'broker_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('broker_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_hash', sa.String(64), nullable=False),
        sa.Column('broker_token_encrypted', sa.Text(), nullable=True),
        sa.Column('broker_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('broker_refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('broker_refresh_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('connection_id', 'session_hash', name='uq_broker_token_per_session'),
    )
    op.create_index('ix_broker_tokens_connection_id', 'broker_tokens', ['connection_id'])
    op.create_index('ix_broker_tokens_session_hash', 'broker_tokens', ['session_hash'])

    # 3. Add broker_connection_id to user_sessions (nullable — backward compatible)
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('broker_connection_id', sa.String(36), nullable=True))
        batch_op.create_foreign_key('fk_user_sessions_connection', 'broker_connections', ['broker_connection_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_sessions_connection', type_='foreignkey')
        batch_op.drop_column('broker_connection_id')

    op.drop_table('broker_tokens')
    op.drop_table('broker_connections')
