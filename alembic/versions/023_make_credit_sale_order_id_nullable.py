"""make credit_sale order_id nullable for WhatsApp-originated debts

Revision ID: 023_make_credit_sale_order_id_nullable
Revises: 022_add_order_reminder_sent_at
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op

revision = "023_make_credit_sale_order_id_nullable"
down_revision = "022_add_order_reminder_sent_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_credit_sales_order_id", "credit_sales", type_="unique")
    op.alter_column(
        "credit_sales",
        "order_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    # Re-add unique but only for non-null order_ids
    op.create_index(
        "ix_credit_sales_order_id_unique",
        "credit_sales",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_credit_sales_order_id_unique", table_name="credit_sales")
    op.alter_column(
        "credit_sales",
        "order_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.create_unique_constraint("uq_credit_sales_order_id", "credit_sales", ["order_id"])
