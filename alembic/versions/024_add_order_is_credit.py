"""add is_credit flag to orders

Revision ID: 024_add_order_is_credit
Revises: 023_make_credit_sale_order_id_nullable
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op

revision = "024_add_order_is_credit"
down_revision = "023_make_credit_sale_order_id_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("is_credit", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("orders", "is_credit")
