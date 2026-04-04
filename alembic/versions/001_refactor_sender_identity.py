"""refactor: separate sender identity from message role

Revision ID: 001_refactor_sender_identity
Revises:
Create Date: 2026-04-04

Changes
-------
conversations
  - RENAME phone_number → customer_identifier
  - ADD    customer_name VARCHAR(120) NULLABLE
  - RENAME index ix_conversations_tenant_phone_channel
         → ix_conversations_tenant_identifier_channel

messages
  - RENAME sender      → sender_role
  - ADD    sender_identifier VARCHAR(40) NULLABLE

Rollback (downgrade) reverses all of the above.
"""

from alembic import op
import sqlalchemy as sa

revision = "001_refactor_sender_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── conversations ─────────────────────────────────────────────────────────
    op.alter_column(
        "conversations",
        "phone_number",
        new_column_name="customer_identifier",
        existing_type=sa.String(40),
        existing_nullable=False,
    )
    op.add_column(
        "conversations",
        sa.Column("customer_name", sa.String(120), nullable=True),
    )
    op.drop_index(
        "ix_conversations_tenant_phone_channel",
        table_name="conversations",
    )
    op.create_index(
        "ix_conversations_tenant_identifier_channel",
        "conversations",
        ["tenant_id", "customer_identifier", "channel"],
    )

    # ── messages ──────────────────────────────────────────────────────────────
    op.alter_column(
        "messages",
        "sender",
        new_column_name="sender_role",
        existing_type=sa.String(20),
        existing_nullable=False,
    )
    op.add_column(
        "messages",
        sa.Column("sender_identifier", sa.String(40), nullable=True),
    )


def downgrade() -> None:
    # ── messages ──────────────────────────────────────────────────────────────
    op.drop_column("messages", "sender_identifier")
    op.alter_column(
        "messages",
        "sender_role",
        new_column_name="sender",
        existing_type=sa.String(20),
        existing_nullable=False,
    )

    # ── conversations ─────────────────────────────────────────────────────────
    op.drop_index(
        "ix_conversations_tenant_identifier_channel",
        table_name="conversations",
    )
    op.create_index(
        "ix_conversations_tenant_phone_channel",
        "conversations",
        ["tenant_id", "customer_identifier", "channel"],
    )
    op.drop_column("conversations", "customer_name")
    op.alter_column(
        "conversations",
        "customer_identifier",
        new_column_name="phone_number",
        existing_type=sa.String(40),
        existing_nullable=False,
    )
