"""add google_sub to users for Google OAuth

Revision ID: b8c9f1d2e34a
Revises: a0deb75ad22f
Create Date: 2026-08-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9f1d2e34a'
down_revision: Union[str, None] = ['a0deb75ad22f', 'f7a3c2d1e94b']
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add google_sub column for Google OAuth identity."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('google_sub', sa.String(128), nullable=True))
        batch_op.create_index(
            'ix_users_google_sub',
            ['google_sub'],
            unique=True,
            postgresql_where='google_sub IS NOT NULL',
        )


def downgrade() -> None:
    """Remove google_sub column."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_google_sub')
        batch_op.drop_column('google_sub')
