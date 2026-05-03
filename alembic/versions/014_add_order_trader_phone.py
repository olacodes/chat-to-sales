"""add trader_phone to orders

Revision ID: 014_add_order_trader_phone
Revises: 013_add_phone_to_users
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op

revision = "014_add_order_trader_phone"
down_revision = "013_add_phone_to_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("trader_phone", sa.String(20), nullable=True),
    )
    op.create_index("ix_orders_trader_phone", "orders", ["trader_phone"])


def downgrade() -> None:
    op.drop_index("ix_orders_trader_phone", table_name="orders")
    op.drop_column("orders", "trader_phone")
