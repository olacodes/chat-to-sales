"""add message_reactions table

Revision ID: 007_add_message_reactions
Revises: 006_widen_notification_event_id
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "007_add_message_reactions"
down_revision = "006_widen_notification_event_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_reactions",
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
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("emoji", sa.String(10), nullable=False),
        sa.UniqueConstraint("message_id", "user_id", name="uq_reactions_message_user"),
    )
    op.create_index("ix_reactions_message_id", "message_reactions", ["message_id"])
    op.create_index("ix_reactions_tenant_id", "message_reactions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_reactions_tenant_id", table_name="message_reactions")
    op.drop_index("ix_reactions_message_id", table_name="message_reactions")
    op.drop_table("message_reactions")
