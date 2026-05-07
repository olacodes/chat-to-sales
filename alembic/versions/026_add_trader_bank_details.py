"""add bank details to traders

Revision ID: 026_add_trader_bank_details
Revises: 025_add_order_customer_name
Create Date: 2026-05-07
"""

import sqlalchemy as sa
from alembic import op

revision = "026_add_trader_bank_details"
down_revision = "025_add_order_customer_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traders", sa.Column("bank_name", sa.String(60), nullable=True))
    op.add_column("traders", sa.Column("bank_account_number", sa.String(20), nullable=True))
    op.add_column("traders", sa.Column("bank_account_name", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("traders", "bank_account_name")
    op.drop_column("traders", "bank_account_number")
    op.drop_column("traders", "bank_name")
