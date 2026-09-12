"""merge: capability separation backfill + existing chain

Merge the new capability separation backfill migration with the existing
migration chain.

Revision ID: 3f8a2e9c4d5b
Revises: 9e4d8c2a1f7b, b3e5f8a1c7d2
Create Date: 2026-09-12 15:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3f8a2e9c4d5b"
down_revision: Union[str, None] = ("9e4d8c2a1f7b", "b3e5f8a1c7d2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
