"""add customer_phone to orders and tenant_id to traders

Revision ID: 012_add_order_customer_phone_and_trader_tenant
Revises: 011_add_traders
Create Date: 2026-04-28
"""

import sqlalchemy as sa
from alembic import op

revision = "012_add_order_customer_phone_and_trader_tenant"
down_revision = "011_add_traders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── orders: add customer_phone ────────────────────────────────────────────
    op.add_column(
        "orders",
        sa.Column("customer_phone", sa.String(20), nullable=True),
    )

    # ── traders: add tenant_id + index ────────────────────────────────────────
    op.add_column(
        "traders",
        sa.Column("tenant_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_traders_tenant_id", "traders", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_traders_tenant_id", table_name="traders")
    op.drop_column("traders", "tenant_id")
    op.drop_column("orders", "customer_phone")
