"""add customer_name to orders

Revision ID: 025_add_order_customer_name
Revises: 024_add_order_is_credit
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op

revision = "025_add_order_customer_name"
down_revision = "024_add_order_is_credit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("customer_name", sa.String(120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "customer_name")
