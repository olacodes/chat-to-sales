"""add invite_tokens table

Revision ID: 008_add_invite_tokens
Revises: 007_add_message_reactions
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "008_add_invite_tokens"
down_revision = "007_add_message_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invite_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
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
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invite_tokens_tenant_id", "invite_tokens", ["tenant_id"])
    op.create_index("ix_invite_tokens_token", "invite_tokens", ["token"])


def downgrade() -> None:
    op.drop_index("ix_invite_tokens_token", table_name="invite_tokens")
    op.drop_index("ix_invite_tokens_tenant_id", table_name="invite_tokens")
    op.drop_table("invite_tokens")
