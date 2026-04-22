"""add assigned_to_user_id to conversations

Revision ID: 004_add_conversation_assignment
Revises: 003_add_auth_tables
Create Date: 2026-04-22
"""

import sqlalchemy as sa
from alembic import op

revision = "004_add_conversation_assignment"
down_revision = "003_add_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "assigned_to_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversations_assigned_to",
        "conversations",
        ["assigned_to_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_assigned_to", table_name="conversations")
    op.drop_column("conversations", "assigned_to_user_id")
