"""merge: day41.2 cross-D1 lock with broker authorizations

Revision ID: a3b4c5d6e7f8
Revises: e2b4c6d8f0a1, f1a2b3c4d5e6
Create Date: 2026-09-16

Single-head cleanup: two parallel work sessions each extended the
branchpoint ``5e2a7b9c3f4d`` — day41.2 cross-D1 family lock/S2 evidence
(``e2b4c6d8f0a1``) and the BrokerAuthorization architecture
(``f1a2b3c4d5e6``). ``alembic upgrade head`` (startup ``init_db`` and
every pipeline-driving test) raised ``MultipleHeads`` while both heads
existed.

This is a pure merge node (the repo's established convention — see
``3f8a2e9c4d5b``, ``9b675f8a3af0``, ``merge_day38_gex``): it carries NO
DDL of its own. Both branches' migrations already apply their schema
exactly once; this node only makes ``head`` unambiguous.
"""
from typing import Sequence, Union

from alembic import op  # noqa: F401  (kept for revision-file convention)
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = ("e2b4c6d8f0a1", "f1a2b3c4d5e6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge node — no DDL. Both parent branches are complete migrations.
    pass


def downgrade() -> None:
    # Structural downgrade only: reopens the two branches (no DDL to
    # reverse here). To actually drop either branch's schema, downgrade
    # further to its revision (e2b4c6d8f0a1 / f1a2b3c4d5e6).
    pass
