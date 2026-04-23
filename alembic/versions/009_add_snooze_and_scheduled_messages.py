"""add snooze and scheduled_messages

Revision ID: 009_add_snooze_and_scheduled_messages
Revises: 008_add_invite_tokens
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "009_add_snooze_and_scheduled_messages"
down_revision = "008_add_invite_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Widen alembic_version to hold revision IDs longer than 32 chars ───────
    # This revision's ID is 37 characters; the default VARCHAR(32) column would
    # cause a StringDataRightTruncationError when Alembic writes the new version.
    # Widening here (before Alembic records the stamp) fixes it permanently.
    op.execute(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
    )

    # ── Feature 1: Snooze ─────────────────────────────────────────────────────
    op.add_column(
        "conversations",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversations_tenant_snoozed",
        "conversations",
        ["tenant_id", "snoozed_until"],
    )

    # ── Feature 2: Scheduled Messages ─────────────────────────────────────────
    op.create_table(
        "scheduled_messages",
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
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.create_index(
        "ix_scheduled_messages_tenant_id", "scheduled_messages", ["tenant_id"]
    )
    op.create_index(
        "ix_scheduled_messages_conversation_id",
        "scheduled_messages",
        ["conversation_id"],
    )
    op.create_index(
        "ix_scheduled_messages_status_scheduled_for",
        "scheduled_messages",
        ["status", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduled_messages_status_scheduled_for",
        table_name="scheduled_messages",
    )
    op.drop_index(
        "ix_scheduled_messages_conversation_id", table_name="scheduled_messages"
    )
    op.drop_index("ix_scheduled_messages_tenant_id", table_name="scheduled_messages")
    op.drop_table("scheduled_messages")

    op.drop_index("ix_conversations_tenant_snoozed", table_name="conversations")
    op.drop_column("conversations", "snoozed_until")
