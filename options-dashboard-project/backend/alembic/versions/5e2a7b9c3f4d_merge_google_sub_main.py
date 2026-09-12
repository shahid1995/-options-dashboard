"""merge: google_sub index with main chain

Revision ID: 5e2a7b9c3f4d
Revises: 3f8a2e9c4d5b, c7d3e5f8a9b2
Create Date: 2026-09-12 16:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5e2a7b9c3f4d"
down_revision: Union[str, None] = ("3f8a2e9c4d5b", "c7d3e5f8a9b2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
