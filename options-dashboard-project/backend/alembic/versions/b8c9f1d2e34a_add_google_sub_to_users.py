"""add google_sub to users for Google OAuth (DDL only)

Revision ID: b8c9f1d2e34a
Revises: a0deb75ad22f
Create Date: 2026-08-29 12:00:00.000000

NOTE: This migration contains ONLY DDL (ADD COLUMN).
The corresponding index creation is in revision c7d3e5f8a9b2 to ensure
CockroachDB compatibility (DDL must be committed before indexes can be
created on the new column).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9f1d2e34a'
down_revision: Union[str, None] = ['a0deb75ad22f', '9e4d8c2a1f7b']
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add google_sub column for Google OAuth identity (DDL only)."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('google_sub', sa.String(128), nullable=True))


def downgrade() -> None:
    """Remove google_sub column."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('google_sub')
