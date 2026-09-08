"""merge: day39 broker-sync + day38 gex heads

Revision ID: f7aa24156f6d
Revises: 9b675f8a3af0, merge_day38_gex
Create Date: 2026-09-08 16:50:00.949890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7aa24156f6d'
down_revision: Union[str, None] = ('9b675f8a3af0', 'merge_day38_gex')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
