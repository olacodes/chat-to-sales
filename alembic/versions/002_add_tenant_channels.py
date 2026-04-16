"""add tenant_channels table

Revision ID: 002_add_tenant_channels
Revises: 001_refactor_sender_identity
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op

revision = "002_add_tenant_channels"
down_revision = "001_refactor_sender_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_channels",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # ── tenant scope ──────────────────────────────────────────────────
        sa.Column("tenant_id", sa.String(36), nullable=False),
        # ── channel config ────────────────────────────────────────────────
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("phone_number_id", sa.String(64), nullable=False),
        # Token is stored encrypted — Fernet ciphertext is ~170 chars for
        # a typical Meta access token, but TEXT gives headroom for rotation.
        sa.Column("encrypted_access_token", sa.Text, nullable=False),
        sa.Column(
            "webhook_registered",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Tenant-scoped lookup (most queries filter by tenant_id first)
    op.create_index(
        "ix_tenant_channels_tenant_id",
        "tenant_channels",
        ["tenant_id"],
    )

    # Enforce one config per (tenant, channel) — makes upserts idempotent
    op.create_unique_constraint(
        "uq_tenant_channels_tenant_channel",
        "tenant_channels",
        ["tenant_id", "channel"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_tenant_channels_tenant_channel",
        "tenant_channels",
        type_="unique",
    )
    op.drop_index("ix_tenant_channels_tenant_id", table_name="tenant_channels")
    op.drop_table("tenant_channels")
