"""add credit_sales table

Revision ID: 010_add_credit_sales
Revises: 009_add_snooze_and_scheduled_messages
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "010_add_credit_sales"
down_revision = "009_add_snooze_and_scheduled_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_sales",
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "order_id",
            sa.String(36),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("reminder_interval_days", sa.Integer, nullable=False, server_default="3"),
        sa.Column("max_reminders", sa.Integer, nullable=False, server_default="5"),
        sa.Column("reminders_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_unique_constraint(
        "uq_credit_sales_order_id", "credit_sales", ["order_id"]
    )
    op.create_index("ix_credit_sales_tenant_id", "credit_sales", ["tenant_id"])
    op.create_index(
        "ix_credit_sales_tenant_status", "credit_sales", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_credit_sales_conversation_id", "credit_sales", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_credit_sales_conversation_id", table_name="credit_sales")
    op.drop_index("ix_credit_sales_tenant_status", table_name="credit_sales")
    op.drop_index("ix_credit_sales_tenant_id", table_name="credit_sales")
    op.drop_constraint("uq_credit_sales_order_id", "credit_sales", type_="unique")
    op.drop_table("credit_sales")
