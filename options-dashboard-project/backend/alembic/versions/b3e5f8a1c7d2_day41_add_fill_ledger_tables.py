"""day41: add fill ledger tables (broker_fill_ledger_*, identity alias/lineage)

Revision ID: b3e5f8a1c7d2
Revises: a7c1d9e4f2b8
Create Date: 2026-09-10

Adds the Day40.5/Day40.6 fill-identity architecture:

- broker_fill_ledger_observation: immutable per-NORMALIZED-observation record.
  Deliberately NO unique constraint on (tenant, broker, d1, content_fingerprint)
  — Lane C observations are never delivery-deduped on (D1, FPv2) (Day40.5 §5.2,
  Invariants X/AA).  Two identical no-ID fills ⇒ two rows, always.
- broker_fill_ledger_fill: economic-fill identity row, PK
  (tenant_id, provider_order_id, fill_eq_key).  TRADE_ID rows authoritative;
  COMPOSITE rows provisional quarantine scopes.  PK never mutated in place
  (Day40.3 §4).
- broker_fill_identity_alias: provisional → authoritative alias relation
  (the only mutable pointer in the upgrade model).
- broker_fill_identity_lineage: append-only lineage/audit trail.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3e5f8a1c7d2"
down_revision: Union[str, None] = "a7c1d9e4f2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 1. broker_fill_ledger_observation (immutable) ---------------------
    op.create_table(
        "broker_fill_ledger_observation",
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("raw_observation_id", sa.String(length=36), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("broker", sa.String(length=64), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=False),
        sa.Column("observation_class", sa.String(length=32), nullable=False),
        sa.Column("d1", sa.String(length=64), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_trade_id", sa.String(length=128), nullable=True),
        sa.Column("fill_eq_key", sa.String(length=160), nullable=True),
        sa.Column("fill_quantity", sa.Integer(), nullable=True),
        sa.Column("fill_price", sa.String(length=64), nullable=True),
        sa.Column("cumulative_after", sa.Integer(), nullable=True),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_excerpt", sa.Text(), nullable=True),
        sa.Column("reconciliation_state", sa.String(length=32), nullable=False),
        sa.Column("observed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("observation_id"),
    )
    op.create_index(
        "ix_broker_fill_ledger_observation_raw_observation_id",
        "broker_fill_ledger_observation",
        ["raw_observation_id"],
        unique=False,
    )
    op.create_index(
        "ix_broker_fill_ledger_observation_tenant_id",
        "broker_fill_ledger_observation",
        ["tenant_id"],
        unique=False,
    )
    # Non-unique lookup index (Day40.5 §5.2: NO (d1, fp) uniqueness here).
    op.create_index(
        "ix_bfill_obs_lookup",
        "broker_fill_ledger_observation",
        ["tenant_id", "broker", "provider_order_id", "d1"],
        unique=False,
    )

    # --- 2. broker_fill_ledger_fill (economic identity) ---------------------
    op.create_table(
        "broker_fill_ledger_fill",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=False),
        sa.Column("fill_eq_key", sa.String(length=160), nullable=False),
        sa.Column("fill_identity_type", sa.String(length=16), nullable=False),
        sa.Column("reconciliation_state", sa.String(length=32), nullable=False),
        sa.Column("canonical_id", sa.String(length=64), nullable=True),
        sa.Column("fill_quantity", sa.Integer(), nullable=True),
        sa.Column("fill_price", sa.String(length=64), nullable=True),
        sa.Column("cumulative_after", sa.Integer(), nullable=True),
        sa.Column("observed_count", sa.Integer(), nullable=False),
        sa.Column("frozen_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "provider_order_id", "fill_eq_key"
        ),
    )

    # --- 3. broker_fill_identity_alias (mutable pointer) --------------------
    op.create_table(
        "broker_fill_identity_alias",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=False),
        sa.Column("from_eq_key", sa.String(length=160), nullable=False),
        sa.Column("to_eq_key", sa.String(length=160), nullable=True),
        sa.Column("alias_state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "provider_order_id", "from_eq_key"
        ),
    )

    # --- 4. broker_fill_identity_lineage (append-only audit) ----------------
    op.create_table(
        "broker_fill_identity_lineage",
        sa.Column("lineage_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=True),
        sa.Column("from_eq_key", sa.String(length=160), nullable=False),
        sa.Column("to_eq_key", sa.String(length=160), nullable=True),
        sa.Column("upgrade_trigger", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("trade_ids", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lineage_id"),
    )
    op.create_index(
        "ix_broker_fill_identity_lineage_tenant_id",
        "broker_fill_identity_lineage",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_broker_fill_identity_lineage_tenant_id",
        table_name="broker_fill_identity_lineage",
    )
    op.drop_table("broker_fill_identity_lineage")
    op.drop_table("broker_fill_identity_alias")
    op.drop_table("broker_fill_ledger_fill")
    op.drop_index("ix_bfill_obs_lookup", table_name="broker_fill_ledger_observation")
    op.drop_index(
        "ix_broker_fill_ledger_observation_tenant_id",
        table_name="broker_fill_ledger_observation",
    )
    op.drop_index(
        "ix_broker_fill_ledger_observation_raw_observation_id",
        table_name="broker_fill_ledger_observation",
    )
    op.drop_table("broker_fill_ledger_observation")
