"""broker_authorizations table + carry-forward of session-scoped broker tokens

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-09-15

Broker-authorization architecture (non-destructive):

1. Creates the ``broker_authorizations`` table — the authoritative,
   connection-owned token source. One row per OAuth grant; encrypted
   token material; its own expiry/status lifecycle; never owned by a
   UserSession.

2. Carry-forward: existing session-scoped ``broker_tokens`` rows with
   encrypted token material are copied to ``broker_authorizations``
   (method='migration', status='active'). Encrypted values are copied
   VERBATIM (Fernet blobs — no re-encryption, so no key dependency),
   expiry columns are preserved, and the association with the original
   BrokerConnection is preserved. Legacy rows are NOT deleted — the old
   table remains a read-only fallback for pre-migration sessions.

The copy is idempotent: rows whose (connection_id) already has an active
'migration' authorization are skipped, and rows with the sentinel
connection_id='none' (platform sessions) are ignored.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.identity import BrokerAuthorization, BrokerToken

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, name: str) -> bool:
    inspector = sa.inspect(bind)
    return inspector.has_table(name)


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. DDL: create the table (idempotent guard for re-runs). ---
    if not _table_exists(bind, "broker_authorizations"):
        op.create_table(
            "broker_authorizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "connection_id",
                sa.String(36),
                sa.ForeignKey("broker_connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
            sa.Column("access_token_expires_at", sa.DateTime(), nullable=True),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
            sa.Column("refresh_token_expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="active"
            ),
            sa.Column(
                "method", sa.String(32), nullable=False, server_default="oauth_callback"
            ),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.Column("last_refreshed_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_broker_authorizations_connection_id",
            "broker_authorizations",
            ["connection_id"],
        )
        op.create_index(
            "ix_broker_authorizations_status",
            "broker_authorizations",
            ["status"],
        )

    # --- 2. Carry-forward: copy legacy session-scoped tokens. ---
    if not _table_exists(bind, "broker_tokens"):
        return  # nothing to carry forward

    from datetime import datetime, timezone
    from uuid import uuid4

    now = datetime.now(timezone.utc)
    already_migrated = {
        row[0]
        for row in bind.execute(
            sa.select(BrokerAuthorization.connection_id).where(
                BrokerAuthorization.status == "active",
                BrokerAuthorization.method == "migration",
            )
        )
    }

    source_rows = bind.execute(
        sa.select(
            BrokerToken.connection_id,
            BrokerToken.broker_token_encrypted,
            BrokerToken.broker_token_expires_at,
            BrokerToken.broker_refresh_token_encrypted,
            BrokerToken.broker_refresh_token_expires_at,
            BrokerToken.created_at,
        ).where(BrokerToken.broker_token_encrypted.isnot(None))
    ).fetchall()

    copied = 0
    for row in source_rows:
        (
            connection_id,
            access_enc,
            access_exp,
            refresh_enc,
            refresh_exp,
            created_at,
        ) = row
        if not connection_id or connection_id == "none":
            continue  # platform-session sentinel — never a connection token
        if connection_id in already_migrated:
            continue  # idempotent re-run
        issued_at = created_at or now
        bind.execute(
            sa.insert(BrokerAuthorization).values(
                id=str(uuid4()),
                connection_id=connection_id,
                access_token_encrypted=access_enc,
                access_token_expires_at=access_exp,
                refresh_token_encrypted=refresh_enc,
                refresh_token_expires_at=refresh_exp,
                status="active",
                method="migration",
                issued_at=issued_at,
                last_refreshed_at=None,
                last_used_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        already_migrated.add(connection_id)
        copied += 1

    # Deliberately NO deletion of broker_tokens rows (non-destructive).
    print(f"[f1a2b3c4d5e6] broker_authorizations carry-forward: {copied} row(s) copied")


def downgrade() -> None:
    # Drop only the new table. The carry-forward copied data out of
    # broker_tokens without modifying it, so the downgrade loses nothing.
    bind = op.get_bind()
    if _table_exists(bind, "broker_authorizations"):
        op.drop_index(
            "ix_broker_authorizations_status", table_name="broker_authorizations"
        )
        op.drop_index(
            "ix_broker_authorizations_connection_id",
            table_name="broker_authorizations",
        )
        op.drop_table("broker_authorizations")
